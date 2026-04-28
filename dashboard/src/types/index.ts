export interface Vitals {
  heart_rate?: number;
  spo2?: number;
  blood_pressure_sys?: number;
  blood_pressure_dia?: number;
  temperature?: number;
  respiratory_rate?: number;
}

export interface Movement {
  is_sleeping?: boolean;
  is_fall_detected?: boolean;
  sos_pressed?: boolean;
  last_movement_ago_s?: number;
}

export interface Resident {
  id: string;
  name: string;
  room: string;
  age?: number;
  gender?: string;
  vitals?: Vitals;
  alert_level?: number;
  ml_risk?: number;
  current_zone?: string;
  zone?: string;
  activity?: string;
  time_of_day?: string;
  time_label?: string;
  routine_label?: string;
  care_level?: string;
  dining_table?: string;
  dining_seat?: string;
  meal_mode?: string;
  movement?: Movement;
  movement_scenario?: string;
  scenario?: string;
  scenario_active?: string;
  assigned_movement_scenario?: string;
  assigned_caregiver?: string;
  pathologies?: string[];
  medications?: string[];
  position?: { x: number; z: number; floor: number };
  profile?: {
    age?: number;
    mobility?: string;
    pathologies?: string[];
    life_profile?: { archetype_label?: string; label?: string; supervision?: string };
  };
}

export interface Alert {
  id: string;
  resident_id: string;
  resident_name?: string;
  level: number;
  reason: string;
  created_at: string;
  acknowledged?: boolean;
  ack_by?: string;
  location?: string;
  time_since_s?: number;
  notified_staff?: Record<string, string>;
  resolved?: boolean;
}

export interface HistoryPoint {
  t: number;
  v: number;
}

export interface HistoryBuffer {
  hr: HistoryPoint[];
  spo2: HistoryPoint[];
  bp: HistoryPoint[];
  temp: HistoryPoint[];
}

export type WSMessage =
  | { type: 'resident_update'; resident: Resident }
  | { type: 'alert'; alert: Alert }
  | { type: 'summary'; residents: Resident[]; active_alerts: Alert[] };

export type AlertLevel = 0 | 1 | 2 | 3 | 4 | 5;

export const ALERT_COLORS: Record<number, string> = {
  0: '#10b981',
  1: '#3b82f6',
  2: '#f59e0b',
  3: '#f97316',
  4: '#ef4444',
  5: '#ff0000',
};

export const ALERT_LABELS: Record<number, string> = {
  0: 'Stable',
  1: 'Info',
  2: 'Attention',
  3: 'Alerte',
  4: 'Urgence',
  5: 'Danger vital',
};

export interface Staff {
  id: string;
  name?: string;
  role?: string;
  sector?: string;
  shift?: string;
  status?: string;
  assigned_count?: number;
  active_alerts_count?: number;
  history_count_30d?: number;
  workload_score?: number;
  max_alert_level?: number;
  assigned_residents?: Array<{
    resident_id: string;
    name: string;
    room: string;
    current_zone?: string;
    ml_risk?: number;
    alert_level?: number;
  }>;
  notifications?: Array<{
    level: number;
    resident_name: string;
    location?: string;
    reason?: string;
  }>;
  recent_history?: Array<{
    resident_id: string;
    resident_name: string;
    room: string;
    time: string;
    level: number;
    level_name?: string;
    zone?: string;
    routine?: string;
    event?: string;
    ml_risk?: number;
  }>;
}

export interface ToastData {
  id: string;
  level: number;
  residentName: string;
  reason: string;
}

export interface FamilleResident {
  id: string;
  name: string;
  room: string;
  age?: number;
  gender?: string;
  admission_date?: string;
  referring_physician?: string;
  emergency_contacts?: Array<{ name: string; relation: string; phone: string }>;
  pathologies?: string[];
  week_schedule?: Array<{ day: string; activities: string }>;
  general_status?: string;
  last_seen?: string;
}
