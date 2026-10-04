export const PRIORITIES = [
  "immediate",
  "delayed",
  "minor",
  "unreliable",
] as const;

export type Priority = (typeof PRIORITIES)[number];

export type ScoreSource = "pipeline" | "live";

export type CategoryScores = {
  heartbeat: number;
  oxygen: number;
  temperature: number;
  ecg: number;
  overall_abnormality: number;
};

export type FeatureMap = Record<string, number | null>;

export type HistoryPoint = {
  recordedAt: string;
  heartRate: number | null;
  spo2: number | null;
  temperature: number | null;
};

export type PatientCard = {
  rank: number;
  patientId: string;
  deviceId: string | null;
  displayName: string;
  lastSeenAt: string | null;
  snapshotAt: string | null;
  dataAgeSeconds: number | null;
  live: boolean;
  contact: boolean;
  heartRate: number | null;
  heartRateValid: boolean;
  spo2: number | null;
  spo2Valid: boolean;
  temperature: number | null;
  ecgCount: number;
  patientScore: number;
  scoreSource: ScoreSource;
  categoryScores: CategoryScores;
  features: FeatureMap;
  priority: Priority;
  reasons: string[];
  history: HistoryPoint[];
};

export type TriageSummary = {
  generatedAt: string;
  patients: PatientCard[];
  counts: Record<Priority, number> & { total: number };
};

export type EcgPoint = {
  recordedAt: string;
  sampleIndex: number;
  value: number;
};

export type PatientDetail = {
  patient: PatientCard;
  ecg: EcgPoint[];
};
