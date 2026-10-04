"use client";

import { useEffect, useState } from "react";
import type {
  CategoryScores,
  EcgPoint,
  HistoryPoint,
  PatientCard,
  PatientDetail,
  Priority,
  TriageSummary,
} from "@/lib/types";

const POLL_MS = 3000;

const PRIORITY: Record<
  Priority,
  { label: string; hint: string; tone: string; soft: string; bar: string }
> = {
  immediate: {
    label: "Immediate",
    hint: "Treat first",
    tone: "text-[#f15454]",
    soft: "bg-[#f15454]/12 text-[#ffb4b0] ring-[#f15454]/35",
    bar: "bg-[#f15454]",
  },
  delayed: {
    label: "Delayed",
    hint: "Can wait briefly",
    tone: "text-[#d9a441]",
    soft: "bg-[#d9a441]/12 text-[#f0d08a] ring-[#d9a441]/30",
    bar: "bg-[#d9a441]",
  },
  minor: {
    label: "Minor",
    hint: "Stable",
    tone: "text-[#3dbe86]",
    soft: "bg-[#3dbe86]/12 text-[#9ae6c4] ring-[#3dbe86]/30",
    bar: "bg-[#3dbe86]",
  },
  unreliable: {
    label: "Sensor",
    hint: "Unreliable vitals",
    tone: "text-[#8b95a0]",
    soft: "bg-white/6 text-[#c3cad1] ring-white/10",
    bar: "bg-[#8b95a0]",
  },
};

function formatVital(value: number | null, digits = 0) {
  if (value == null || Number.isNaN(value)) return "—";
  return digits > 0 ? value.toFixed(digits) : String(Math.round(value));
}

function formatAge(seconds: number | null) {
  if (seconds == null) return "no link";
  if (seconds < 2) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.round(seconds / 60)}m`;
}

function scorePercent(score: number) {
  return Math.round(score * 100);
}

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function Sparkline({
  points,
  pick,
  color,
}: {
  points: HistoryPoint[];
  pick: (point: HistoryPoint) => number | null;
  color: string;
}) {
  const values = points
    .map(pick)
    .filter((value): value is number => value != null && Number.isFinite(value));
  if (values.length < 2) {
    return (
      <div className="flex h-12 items-center justify-center text-[11px] text-[#5c6772]">
        No series
      </div>
    );
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coords = values.map((value, index) => {
    const x = (index / (values.length - 1)) * 100;
    const y = 22 - ((value - min) / span) * 18;
    return [x, y] as const;
  });
  const line = coords
    .map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
  const area = `${line} L100,24 L0,24 Z`;

  return (
    <svg viewBox="0 0 100 24" className="h-12 w-full" preserveAspectRatio="none">
      <path d={area} fill={color} opacity="0.14" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function EcgTrace({ points }: { points: EcgPoint[] }) {
  if (points.length < 4) {
    return (
      <div className="inset-panel scanline flex h-44 items-center justify-center text-sm text-[#5c6772]">
        Awaiting ECG stream
      </div>
    );
  }
  const step = Math.max(1, Math.floor(points.length / 360));
  const values = points.filter((_, index) => index % step === 0).map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const d = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 1000;
      const y = 150 - ((value - min) / span) * 128;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="inset-panel scanline relative overflow-hidden">
      <svg viewBox="0 0 1000 180" className="h-44 w-full" preserveAspectRatio="none">
        {Array.from({ length: 9 }, (_, index) => (
          <line
            key={`h-${index}`}
            x1="0"
            x2="1000"
            y1={20 * index}
            y2={20 * index}
            stroke="rgba(61,190,134,0.08)"
            strokeWidth="1"
          />
        ))}
        {Array.from({ length: 21 }, (_, index) => (
          <line
            key={`v-${index}`}
            x1={index * 50}
            x2={index * 50}
            y1="0"
            y2="180"
            stroke="rgba(61,190,134,0.06)"
            strokeWidth="1"
          />
        ))}
        <path
          d={d}
          fill="none"
          stroke="#4ade80"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

function ScoreRing({ score, priority }: { score: number; priority: Priority }) {
  const radius = 34;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(1, Math.max(0, score)));
  const color =
    priority === "immediate"
      ? "#f15454"
      : priority === "delayed"
        ? "#d9a441"
        : priority === "minor"
          ? "#3dbe86"
          : "#8b95a0";

  return (
    <div className="relative h-[88px] w-[88px]">
      <svg viewBox="0 0 88 88" className="h-full w-full -rotate-90">
        <circle cx="44" cy="44" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
        <circle
          cx="44"
          cy="44"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-xl font-medium tabular">{scorePercent(score)}</span>
        <span className="text-[9px] uppercase tracking-[0.16em] text-[#5c6772]">score</span>
      </div>
    </div>
  );
}

function VitalTile({
  label,
  value,
  unit,
  range,
  warn,
  muted,
}: {
  label: string;
  value: string;
  unit: string;
  range: string;
  warn: boolean;
  muted?: boolean;
}) {
  return (
    <div className={`inset-panel px-3 py-3 ${warn ? "shadow-[inset_0_0_0_1px_rgba(241,84,84,0.35)]" : ""}`}>
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-[#7d8b99]">{label}</p>
        {warn ? <span className="h-1.5 w-1.5 rounded-full bg-[#f15454]" /> : null}
      </div>
      <div className="mt-2 flex items-end gap-1.5">
        <span className={`font-mono text-[28px] leading-none font-medium tabular ${muted ? "text-[#8b95a0]" : "text-white"}`}>
          {value}
        </span>
        <span className="mb-0.5 text-[11px] text-[#5c6772]">{unit}</span>
      </div>
      <p className="mt-2 font-mono text-[10px] text-[#5c6772]">{range}</p>
    </div>
  );
}

function CountCell({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: string;
}) {
  return (
    <div className="min-w-[72px] px-3 py-2">
      <p className="text-[10px] uppercase tracking-[0.14em] text-[#5c6772]">{label}</p>
      <p className={`mt-1 font-mono text-lg tabular ${tone}`}>{String(count).padStart(2, "0")}</p>
    </div>
  );
}

export function Dashboard() {
  const [queue, setQueue] = useState<TriageSummary | null>(null);
  const [detail, setDetail] = useState<PatientDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const clock = useClock();

  useEffect(() => {
    let cancelled = false;

    async function loadQueue() {
      try {
        const response = await fetch("/api/triage", { cache: "no-store" });
        const payload = (await response.json()) as TriageSummary & { error?: string };
        if (!response.ok) {
          throw new Error(payload.error ?? "Triage API failed");
        }
        if (cancelled) return;
        setQueue(payload);
        setUpdatedAt(payload.generatedAt);
        setError(null);
        setSelectedId((current) => {
          if (current && payload.patients.some((patient) => patient.patientId === current)) {
            return current;
          }
          return payload.patients[0]?.patientId ?? null;
        });
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error ? loadError.message : "Unable to reach the triage API",
          );
        }
      }
    }

    void loadQueue();
    const timer = window.setInterval(() => {
      void loadQueue();
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;

    async function loadDetail(patientId: string) {
      try {
        const response = await fetch(`/api/triage/${encodeURIComponent(patientId)}`, {
          cache: "no-store",
        });
        if (!response.ok) return;
        const payload = (await response.json()) as PatientDetail;
        if (!cancelled) setDetail(payload);
      } catch {
        // Keep the last successful detail frame if a single poll fails.
      }
    }

    void loadDetail(selectedId);
    const timer = window.setInterval(() => {
      void loadDetail(selectedId);
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId]);

  const selected =
    detail?.patient ??
    queue?.patients.find((patient) => patient.patientId === selectedId) ??
    null;
  const counts = queue?.counts ?? {
    immediate: 0,
    delayed: 0,
    minor: 0,
    unreliable: 0,
    total: 0,
  };

  return (
    <div className="triage-shell relative min-h-full">
      <div className="relative mx-auto flex min-h-screen max-w-[1480px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <header className="panel overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3 px-4 py-3">
            <div className="min-w-[180px]">
              <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[#7aa8b8]">
                StormHacks · Field ops
              </p>
              <h1 className="mt-1 text-[28px] leading-none font-medium tracking-[-0.03em] text-white">
                Rapid Triage
              </h1>
            </div>
            <div className="flex items-end gap-6">
              <div>
                <p className="text-[10px] uppercase tracking-[0.16em] text-[#5c6772]">Local time</p>
                <p className="mt-1 font-mono text-2xl tabular text-white">
                  {clock.toLocaleTimeString([], { hour12: false })}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.16em] text-[#5c6772]">DB sync</p>
                <p className="mt-1 flex items-center gap-2 font-mono text-sm tabular text-[#c5d0d8]">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#3dbe86] opacity-50" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-[#3dbe86]" />
                  </span>
                  {updatedAt
                    ? new Date(updatedAt).toLocaleTimeString([], { hour12: false })
                    : "—:—:—"}
                </p>
              </div>
            </div>
            <div className="flex divide-x divide-white/8">
              <CountCell label="Imm" count={counts.immediate} tone="text-[#f15454]" />
              <CountCell label="Delay" count={counts.delayed} tone="text-[#d9a441]" />
              <CountCell label="Minor" count={counts.minor} tone="text-[#3dbe86]" />
              <CountCell label="Sensor" count={counts.unreliable} tone="text-[#8b95a0]" />
            </div>
          </div>
        </header>

        {error ? (
          <div className="mt-4 px-4 py-3 text-sm text-[#ffb4b0] shadow-[inset_0_0_0_1px_rgba(241,84,84,0.35)]">
            {error}
          </div>
        ) : null}

        <div className="mt-4 grid flex-1 items-start gap-4 xl:grid-cols-[minmax(340px,0.86fr)_minmax(520px,1.14fr)]">
          <section className="panel flex flex-col xl:min-h-[640px]">
            <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
              <div>
                <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-[#8794a1]">
                  Priority queue
                </h2>
                <p className="mt-1 text-sm text-[#c5d0d8]">Highest need first</p>
              </div>
              <p className="font-mono text-xs tabular text-[#5c6772]">
                {String(counts.total).padStart(2, "0")} active
              </p>
            </div>
            <div className="flex-1 space-y-2 p-3">
              {queue == null && !error ? (
                <div className="inset-panel px-4 py-12 text-center text-sm text-[#8794a1]">
                  Establishing TimescaleDB link…
                </div>
              ) : null}
              {queue && queue.patients.length === 0 ? (
                <div className="inset-panel px-4 py-12 text-center">
                  <p className="text-sm text-white">No wearables on channel</p>
                  <p className="mt-2 font-mono text-xs text-[#5c6772]">health_readings · 15m window</p>
                </div>
              ) : null}
              {queue?.patients.map((patient) => (
                <PatientRow
                  key={patient.patientId}
                  patient={patient}
                  selected={patient.patientId === selectedId}
                  onSelect={() => setSelectedId(patient.patientId)}
                />
              ))}
            </div>
          </section>

          <section className="panel p-4 xl:min-h-[640px]">
            {selected ? (
              <PatientPanel patient={selected} ecg={detail?.ecg ?? []} />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[#5c6772]">
                Select a device from the queue
              </div>
            )}
          </section>
        </div>

        <footer className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-3 text-[11px] text-[#5c6772]">
          <p>
            Prototype scoring · thresholds from <span className="font-mono">pipeline.py</span> · not clinical advice
          </p>
          <p className="font-mono tabular">poll {POLL_MS / 1000}s · Tiger Cloud</p>
        </footer>
      </div>
    </div>
  );
}

function PatientRow({
  patient,
  selected,
  onSelect,
}: {
  patient: PatientCard;
  selected: boolean;
  onSelect: () => void;
}) {
  const tone = PRIORITY[patient.priority];
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full overflow-hidden text-left transition ${
        selected ? "bg-[#161d25] shadow-[inset_0_0_0_1px_rgba(122,168,184,0.45)]" : "inset-panel hover:bg-[#151b22]"
      }`}
    >
      <div className="flex">
        <div className={`w-1 ${tone.bar}`} />
        <div className="flex-1 px-3 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-baseline gap-3">
              <span className="font-mono text-[22px] font-medium tabular text-white/90">
                {String(patient.rank).padStart(2, "0")}
              </span>
              <div>
                <p className="text-[15px] font-medium tracking-[-0.02em] text-white">
                  {patient.displayName}
                </p>
                <p className="font-mono text-[10px] text-[#5c6772]">{patient.patientId}</p>
              </div>
            </div>
            <div className="text-right">
              <span className={`inline-flex rounded-sm px-1.5 py-0.5 text-[10px] uppercase tracking-[0.12em] ring-1 ${tone.soft}`}>
                {tone.label}
              </span>
              <p className="mt-1 font-mono text-[10px] tabular text-[#5c6772]">
                {patient.live ? "LIVE" : "STALE"} {formatAge(patient.dataAgeSeconds)}
              </p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2 font-mono text-[13px] tabular">
            <MiniVital label="HR" value={formatVital(patient.heartRate)} warn={isHrWarn(patient)} />
            <MiniVital label="SpO₂" value={formatVital(patient.spo2)} warn={isSpo2Warn(patient)} />
            <MiniVital label="Temp" value={formatVital(patient.temperature, 1)} warn={isTempWarn(patient)} />
            <MiniVital label="Idx" value={String(scorePercent(patient.patientScore))} />
          </div>
        </div>
      </div>
    </button>
  );
}

function MiniVital({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="bg-black/20 px-2 py-1.5">
      <p className="text-[9px] uppercase tracking-[0.12em] text-[#5c6772]">{label}</p>
      <p className={warn ? "text-[#ffb4b0]" : "text-[#e8eef3]"}>{value}</p>
    </div>
  );
}

function isHrWarn(patient: PatientCard) {
  return (
    patient.heartRateValid &&
    patient.heartRate != null &&
    (patient.heartRate < 50 || patient.heartRate > 120)
  );
}

function isSpo2Warn(patient: PatientCard) {
  return patient.spo2Valid && patient.spo2 != null && patient.spo2 < 94;
}

function isTempWarn(patient: PatientCard) {
  return (
    patient.temperature != null &&
    patient.temperature >= 32 &&
    (patient.temperature < 35 || patient.temperature > 38)
  );
}

function PatientPanel({
  patient,
  ecg,
}: {
  patient: PatientCard;
  ecg: EcgPoint[];
}) {
  const tone = PRIORITY[patient.priority];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-[#8794a1]">
            Patient console · {String(patient.rank).padStart(2, "0")}
          </p>
          <h3 className="mt-1 text-[30px] leading-none font-medium tracking-[-0.03em] text-white">
            {patient.displayName}
          </h3>
          <p className="mt-2 font-mono text-[11px] text-[#5c6772]">
            {patient.deviceId ? `${patient.deviceId} · ` : ""}
            {patient.patientId}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <span className={`inline-flex rounded-sm px-2 py-1 text-[10px] uppercase tracking-[0.14em] ring-1 ${tone.soft}`}>
              {tone.label} · {tone.hint}
            </span>
            <p className="mt-2 font-mono text-[11px] text-[#5c6772]">
              {patient.scoreSource === "pipeline" ? "PIPELINE" : "LIVE VITALS"} ·{" "}
              {patient.contact ? "CONTACT" : "NO CONTACT"}
            </p>
          </div>
          <ScoreRing score={patient.patientScore} priority={patient.priority} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <VitalTile
          label="Heart rate"
          value={formatVital(patient.heartRate)}
          unit="bpm"
          range="band 50–120"
          warn={isHrWarn(patient)}
          muted={!patient.heartRateValid}
        />
        <VitalTile
          label="SpO₂"
          value={formatVital(patient.spo2)}
          unit="%"
          range="floor 94"
          warn={isSpo2Warn(patient)}
          muted={!patient.spo2Valid}
        />
        <VitalTile
          label="Temp"
          value={formatVital(patient.temperature, 1)}
          unit="°C"
          range="band 35.0–38.0"
          warn={isTempWarn(patient)}
        />
        <VitalTile
          label="Link"
          value={patient.live ? "LIVE" : "HOLD"}
          unit={formatAge(patient.dataAgeSeconds)}
          range={patient.contact ? "skin contact" : "no contact"}
          warn={!patient.live || !patient.contact}
        />
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <div className="inset-panel space-y-3 p-3">
          {categoryEntries(patient.categoryScores).map(([label, value]) => (
            <ScoreMeter key={label} label={label} value={value} />
          ))}
        </div>
        <div className="inset-panel p-3">
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[#7d8b99]">
            Assessment
          </p>
          <ul className="mt-3 space-y-2.5">
            {patient.reasons.slice(0, 5).map((reason) => (
              <li key={reason} className="flex gap-2 text-[13px] leading-5 text-[#c5d0d8]">
                <span className={`mt-1.5 h-1 w-1 shrink-0 ${tone.bar}`} />
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <TrendCard label="HR" unit="bpm" points={patient.history} pick={(point) => point.heartRate} color="#f15454" />
        <TrendCard label="SpO₂" unit="%" points={patient.history} pick={(point) => point.spo2} color="#7aa8b8" />
        <TrendCard label="Temp" unit="°C" points={patient.history} pick={(point) => point.temperature} color="#d9a441" />
      </div>

      <div>
        <div className="mb-2 flex items-end justify-between">
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[#7d8b99]">
            ECG monitor
          </p>
          <p className="font-mono text-[10px] tabular text-[#5c6772]">
            {ecg.length} smp · pkt {patient.ecgCount}
          </p>
        </div>
        <EcgTrace points={ecg} />
      </div>
    </div>
  );
}

function categoryEntries(scores: CategoryScores) {
  return [
    ["Heartbeat", scores.heartbeat],
    ["Oxygen", scores.oxygen],
    ["Temperature", scores.temperature],
    ["ECG", scores.ecg],
  ] as const;
}

function ScoreMeter({ label, value }: { label: string; value: number }) {
  const tone =
    value >= 0.55 ? "bg-[#f15454]" : value >= 0.28 ? "bg-[#d9a441]" : "bg-[#3dbe86]";
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.12em] text-[#7d8b99]">
        <span>{label}</span>
        <span className="font-mono tabular text-[#c5d0d8]">{scorePercent(value)}</span>
      </div>
      <div className="mt-1.5 h-[3px] overflow-hidden bg-white/8">
        <div className={`h-full ${tone}`} style={{ width: `${scorePercent(value)}%` }} />
      </div>
    </div>
  );
}

function TrendCard({
  label,
  unit,
  points,
  pick,
  color,
}: {
  label: string;
  unit: string;
  points: HistoryPoint[];
  pick: (point: HistoryPoint) => number | null;
  color: string;
}) {
  const latest = [...points].reverse().find((point) => pick(point) != null);
  const latestValue = latest ? pick(latest) : null;
  return (
    <div className="inset-panel p-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-[0.12em] text-[#5c6772]">
          {label} · 3m
        </p>
        <p className="font-mono text-[11px] tabular text-[#c5d0d8]">
          {formatVital(latestValue, label === "Temp" ? 1 : 0)}{" "}
          <span className="text-[#5c6772]">{unit}</span>
        </p>
      </div>
      <Sparkline points={points} pick={pick} color={color} />
    </div>
  );
}
