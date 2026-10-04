import { getPool } from "./db";
import type {
  CategoryScores,
  FeatureMap,
  HistoryPoint,
  PatientCard,
  PatientDetail,
  Priority,
  ScoreSource,
  TriageSummary,
} from "./types";

/** Matches backend_serv/pipeline.py PipelineConfig defaults. */
const CONFIG = {
  heartRateLow: 50,
  heartRateHigh: 120,
  spo2Low: 94,
  temperatureLow: 35,
  temperatureHigh: 38,
  snapshotFreshSeconds: 20,
  liveSeconds: 8,
  activeWindow: "15 minutes",
  historyWindow: "3 minutes",
} as const;

const EMPTY_SCORES: CategoryScores = {
  heartbeat: 0,
  oxygen: 0,
  temperature: 0,
  ecg: 0,
  overall_abnormality: 0,
};

type ReadingJoinRow = {
  patient_id: string;
  device_id: string | null;
  last_seen_at: Date | null;
  heart_rate_bpm: number | null;
  spo2_percent: number | null;
  temperature_c: number | null;
  contact: boolean | null;
  heart_rate_valid: boolean | null;
  spo2_valid: boolean | null;
  ecg_count: number | null;
  snapshot_at: Date | null;
  features: FeatureMap | null;
  category_scores: Partial<CategoryScores> | null;
  patient_score: number | null;
};

type HistoryRow = {
  patient_id: string;
  recorded_at: Date;
  heart_rate_bpm: number | null;
  spo2_percent: number | null;
  temperature_c: number | null;
};

function asIso(value: Date | null | undefined) {
  return value ? value.toISOString() : null;
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function severity(value: number | null, low: number, high: number) {
  if (value == null || Number.isNaN(value)) return 0;
  if (value >= low && value <= high) return 0;
  const distance = value < low ? low - value : value - high;
  return clamp01(distance / Math.max(high - low, 1e-9));
}

function mean(values: number[]) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function displayName(patientId: string, deviceId: string | null) {
  if (deviceId && deviceId !== patientId) return deviceId;
  return patientId.replace(/^patient_/i, "");
}

function mergeCategoryScores(
  scores: Partial<CategoryScores> | null,
): CategoryScores {
  return {
    ...EMPTY_SCORES,
    ...scores,
  };
}

function fallbackScore(input: {
  contact: boolean;
  heartRate: number | null;
  heartRateValid: boolean;
  spo2: number | null;
  spo2Valid: boolean;
  temperature: number | null;
}) {
  const reasons: string[] = [];
  const parts: number[] = [];

  if (!input.contact) {
    reasons.push("No skin contact — reseat the wearable before trusting vitals");
    return { score: 0.12, reasons };
  }

  if (input.heartRateValid && input.heartRate != null) {
    const score = severity(
      input.heartRate,
      CONFIG.heartRateLow,
      CONFIG.heartRateHigh,
    );
    parts.push(score);
    if (input.heartRate < CONFIG.heartRateLow) {
      reasons.push(`Heart rate ${Math.round(input.heartRate)} bpm is below ${CONFIG.heartRateLow}`);
    } else if (input.heartRate > CONFIG.heartRateHigh) {
      reasons.push(`Heart rate ${Math.round(input.heartRate)} bpm is above ${CONFIG.heartRateHigh}`);
    }
  }

  if (input.spo2Valid && input.spo2 != null) {
    const score = severity(input.spo2, CONFIG.spo2Low, 100);
    parts.push(score);
    if (input.spo2 < CONFIG.spo2Low) {
      reasons.push(`SpO₂ ${Math.round(input.spo2)}% is below ${CONFIG.spo2Low}%`);
    }
  }

  if (input.temperature != null) {
    const plausible = input.temperature >= 32 && input.temperature <= 42;
    if (!plausible && !input.heartRateValid && !input.spo2Valid) {
      reasons.push(
        `Temperature ${input.temperature.toFixed(1)}°C looks ambient — wait for a body reading`,
      );
    } else {
      const score = severity(
        input.temperature,
        CONFIG.temperatureLow,
        CONFIG.temperatureHigh,
      );
      parts.push(score);
      if (input.temperature < CONFIG.temperatureLow) {
        reasons.push(`Temperature ${input.temperature.toFixed(1)}°C is low`);
      } else if (input.temperature > CONFIG.temperatureHigh) {
        reasons.push(`Temperature ${input.temperature.toFixed(1)}°C is high`);
      }
    }
  }

  const score = parts.length
    ? Math.max(mean(parts), Math.max(...parts) * 0.8)
    : 0;
  return { score, reasons };
}

function featureReasons(features: FeatureMap) {
  const reasons: string[] = [];
  const irregularity = features.ecg_irregularity;
  if (irregularity != null && irregularity > 0.2) {
    reasons.push("ECG interval irregularity is elevated");
  }
  const quality = features.ecg_signal_quality;
  if (quality != null && quality < 0.4) {
    reasons.push("ECG signal quality is weak");
  }
  const deteriorating = features.num_deteriorating_metrics;
  if (deteriorating != null && deteriorating >= 1) {
    reasons.push("One or more vitals are trending worse");
  }
  return reasons;
}

function classifyPriority(input: {
  score: number;
  contact: boolean;
  live: boolean;
  hasValidVital: boolean;
}): Priority {
  if (!input.live) return "unreliable";
  if (!input.hasValidVital) return "unreliable";
  if (input.score >= 0.55) return "immediate";
  if (input.score >= 0.28) return "delayed";
  return "minor";
}

function priorityRank(priority: Priority) {
  switch (priority) {
    case "immediate":
      return 0;
    case "delayed":
      return 1;
    case "unreliable":
      return 2;
    case "minor":
      return 3;
  }
}

function toNumber(value: number | string | null | undefined) {
  if (value == null) return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildPatient(
  row: ReadingJoinRow,
  history: HistoryPoint[],
  now: Date,
): Omit<PatientCard, "rank"> {
  const features = row.features ?? {};
  const lastSeenAt = row.last_seen_at;
  const dataAgeSeconds = lastSeenAt
    ? Math.max(0, (now.getTime() - lastSeenAt.getTime()) / 1000)
    : null;
  const snapshotAgeSeconds = row.snapshot_at
    ? Math.max(0, (now.getTime() - row.snapshot_at.getTime()) / 1000)
    : null;
  const live = dataAgeSeconds != null && dataAgeSeconds <= CONFIG.liveSeconds;
  const contact = Boolean(row.contact);
  const heartRate =
    toNumber(row.heart_rate_bpm) ?? toNumber(features.hr_current);
  const spo2 = toNumber(row.spo2_percent) ?? toNumber(features.spo2_current);
  const temperature =
    toNumber(row.temperature_c) ?? toNumber(features.temp_current);
  const heartRateValid = Boolean(row.heart_rate_valid) && heartRate != null;
  const spo2Valid = Boolean(row.spo2_valid) && spo2 != null;
  const snapshotFresh =
    snapshotAgeSeconds != null &&
    snapshotAgeSeconds <= CONFIG.snapshotFreshSeconds &&
    row.patient_score != null;

  const liveAssessment = fallbackScore({
    contact,
    heartRate,
    heartRateValid,
    spo2,
    spo2Valid,
    temperature,
  });

  const scoreSource: ScoreSource = snapshotFresh ? "pipeline" : "live";
  const patientScore = snapshotFresh
    ? clamp01(Number(row.patient_score))
    : liveAssessment.score;

  const reasons = [
    ...liveAssessment.reasons,
    ...featureReasons(features),
  ];
  if (snapshotFresh) {
    reasons.unshift("Ranked by the 5-second feature pipeline");
  } else if (row.snapshot_at) {
    reasons.unshift("Pipeline snapshot is stale; ranking from latest vitals");
  } else {
    reasons.unshift("No pipeline snapshot yet; ranking from latest vitals");
  }
  if (dataAgeSeconds != null && dataAgeSeconds > CONFIG.liveSeconds) {
    reasons.push(`Last packet was ${Math.round(dataAgeSeconds)}s ago`);
  }

  const plausibleTemp =
    temperature != null && temperature >= 32 && temperature <= 42;
  const hasValidVital = heartRateValid || spo2Valid || (contact && plausibleTemp);
  const liveCategories: CategoryScores = {
    heartbeat: heartRateValid ? severity(heartRate, CONFIG.heartRateLow, CONFIG.heartRateHigh) : 0,
    oxygen: spo2Valid ? severity(spo2, CONFIG.spo2Low, 100) : 0,
    temperature: plausibleTemp
      ? severity(temperature, CONFIG.temperatureLow, CONFIG.temperatureHigh)
      : 0,
    ecg: clamp01(Number(features.ecg_irregularity ?? 0) / 0.2),
    overall_abnormality: patientScore,
  };
  const priority = classifyPriority({
    score: patientScore,
    contact,
    live,
    hasValidVital,
  });

  return {
    patientId: row.patient_id,
    deviceId: row.device_id,
    displayName: displayName(row.patient_id, row.device_id),
    lastSeenAt: asIso(lastSeenAt),
    snapshotAt: asIso(row.snapshot_at),
    dataAgeSeconds,
    live,
    contact,
    heartRate,
    heartRateValid,
    spo2,
    spo2Valid,
    temperature,
    ecgCount: row.ecg_count ?? 0,
    patientScore,
    scoreSource,
    categoryScores: snapshotFresh
      ? mergeCategoryScores(row.category_scores)
      : liveCategories,
    features,
    priority,
    reasons: [...new Set(reasons)],
    history,
  };
}

export async function getTriageQueue(): Promise<TriageSummary> {
  const pool = getPool();
  const now = new Date();
  const { rows } = await pool.query<ReadingJoinRow>(
    `
    WITH latest_readings AS (
      SELECT DISTINCT ON (patient_id)
        patient_id,
        device_id,
        recorded_at AS last_seen_at,
        heart_rate_bpm,
        spo2_percent,
        temperature_c,
        contact,
        heart_rate_valid,
        spo2_valid,
        ecg_count
      FROM public.health_readings
      WHERE recorded_at >= NOW() - INTERVAL '${CONFIG.activeWindow}'
      ORDER BY patient_id, recorded_at DESC
    ),
    latest_snapshots AS (
      SELECT DISTINCT ON (patient_id)
        patient_id,
        calculated_at AS snapshot_at,
        features,
        category_scores,
        patient_score
      FROM public.patient_feature_snapshots
      WHERE calculated_at >= NOW() - INTERVAL '${CONFIG.activeWindow}'
      ORDER BY patient_id, calculated_at DESC
    )
    SELECT
      COALESCE(r.patient_id, s.patient_id) AS patient_id,
      r.device_id,
      r.last_seen_at,
      r.heart_rate_bpm,
      r.spo2_percent,
      r.temperature_c,
      r.contact,
      r.heart_rate_valid,
      r.spo2_valid,
      r.ecg_count,
      s.snapshot_at,
      s.features,
      s.category_scores,
      s.patient_score
    FROM latest_readings r
    FULL OUTER JOIN latest_snapshots s ON s.patient_id = r.patient_id
    `,
  );

  const patientIds = rows.map((row) => row.patient_id);
  const historyByPatient = new Map<string, HistoryPoint[]>();
  if (patientIds.length) {
    const history = await pool.query<HistoryRow>(
      `
      SELECT patient_id, recorded_at, heart_rate_bpm, spo2_percent, temperature_c
      FROM public.health_readings
      WHERE patient_id = ANY($1::text[])
        AND recorded_at >= NOW() - INTERVAL '${CONFIG.historyWindow}'
      ORDER BY recorded_at ASC
      `,
      [patientIds],
    );
    for (const row of history.rows) {
      const points = historyByPatient.get(row.patient_id) ?? [];
      points.push({
        recordedAt: row.recorded_at.toISOString(),
        heartRate: toNumber(row.heart_rate_bpm),
        spo2: toNumber(row.spo2_percent),
        temperature: toNumber(row.temperature_c),
      });
      historyByPatient.set(row.patient_id, points);
    }
  }

  const patients = rows
    .map((row) => buildPatient(row, historyByPatient.get(row.patient_id) ?? [], now))
    .sort((left, right) => {
      const priorityDelta =
        priorityRank(left.priority) - priorityRank(right.priority);
      if (priorityDelta !== 0) return priorityDelta;
      if (right.patientScore !== left.patientScore) {
        return right.patientScore - left.patientScore;
      }
      return (left.dataAgeSeconds ?? 9999) - (right.dataAgeSeconds ?? 9999);
    })
    .map((patient, index) => ({ ...patient, rank: index + 1 }));

  const counts = {
    immediate: 0,
    delayed: 0,
    minor: 0,
    unreliable: 0,
    total: patients.length,
  };
  for (const patient of patients) {
    counts[patient.priority] += 1;
  }

  return {
    generatedAt: now.toISOString(),
    patients,
    counts,
  };
}

export async function getPatientDetail(
  patientId: string,
): Promise<PatientDetail | null> {
  const queue = await getTriageQueue();
  const patient = queue.patients.find((item) => item.patientId === patientId);
  if (!patient) return null;

  const { rows } = await getPool().query<{
    recorded_at: Date;
    sample_index: number;
    sample_value: number;
  }>(
    `
    SELECT recorded_at, sample_index, sample_value
    FROM public.ecg_samples
    WHERE patient_id = $1
      AND recorded_at >= NOW() - INTERVAL '3 seconds'
    ORDER BY recorded_at DESC, sample_index DESC
    LIMIT 800
    `,
    [patientId],
  );

  const ecg = rows
    .slice()
    .reverse()
    .map((row) => ({
      recordedAt: row.recorded_at.toISOString(),
      sampleIndex: row.sample_index,
      value: Number(row.sample_value),
    }));

  return { patient, ecg };
}
