export interface User {
  user_id: string;
  email: string;
  phone?: string;
  first_name: string;
  last_name: string;
  monthly_budget_limit: string;
  created_at: string;
}

export type ChannelType = 'Physical_Store' | 'Online_Ecommerce';

export interface Store {
  store_id: number;
  store_name: string;
  channel_type: ChannelType;
  created_at: string;
}

export interface Category {
  category_id: number;
  category_name: string;
  is_essential: boolean;
}

export interface ReceiptItem {
  item_id?: number;
  receipt?: number;
  /** pk or category name — the backend match-or-creates by name */
  category: number | string;
  category_name?: string;
  item_name: string;
  unit_price: string | number;
  quantity: number;
  line_total?: string;
  is_impulse: boolean;
}

export type SourceType = 'camera' | 'upload';

export interface Receipt {
  receipt_id: number;
  user: string;
  store: number;
  store_name?: string;
  purchase_date: string;
  total_amount: string;
  source_type: SourceType;
  image_url: string | null;
  receipt_image?: string | null;
  verified: boolean;
  created_at: string;
  /** Slip identity — cashier, branch, slip number, payment (return-slip use) */
  cashier_name?: string;
  branch_name?: string;
  slip_number?: string;
  payment_method?: string;
  /** Verbatim line-by-line transcription of the slip as printed */
  original_text?: string;
  items: ReceiptItem[];
}

export interface MonthlyAnalytics {
  audit_month: string;
  total_spent: string;
  impulse_spend: string;
  monthly_budget_limit: string;
  budget_variance: string;
}

export interface CategoryBreakdown {
  category_name: string;
  is_essential: boolean;
  total: string;
  item_count: number;
}

export interface StoreBreakdown {
  store_name: string;
  channel_type: string;
  total: string;
  receipt_count: number;
}

export interface MonthBreakdown {
  year: number;
  month: number;
  total_spent: string;
  impulse_spend: string;
  essential_spend: string;
  budget_limit: string;
  budget_variance: string;
  daily_totals: Record<string, string>;
  categories: CategoryBreakdown[];
  stores: StoreBreakdown[];
  channels: Record<string, string>;
  biggest_purchase: {
    item_name: string;
    line_total: string;
    store_name: string;
    purchase_date: string;
  } | null;
}

/** One "cut X to save Y" suggestion from /receipts/budget_advice/. */
export interface BudgetSuggestion {
  kind: 'category_cut' | 'impulse' | 'pacing' | 'store_frequency' | 'trend';
  title: string;
  detail: string;
  potential_saving: string;
}

export interface BudgetAdvice {
  year: number;
  month: number;
  budget_limit: string;
  total_spent: string;
  has_budget: boolean;
  suggestions: BudgetSuggestion[];
  potential_total_saving: string;
}

export interface LoyaltyDraft {
  points: number;
  label?: string;
  expires_at?: string | null;
}

export interface OcrDraft {
  merchant_name: string | null;
  purchase_date: string | null;
  total_amount: number | null;
  channel_type?: ChannelType | null;
  cashier?: string | null;
  branch?: string | null;
  slip_number?: string | null;
  payment_method?: string | null;
  original_lines?: string[];
  items: { name: string; price: number; category?: string | null; is_impulse?: boolean }[];
  loyalty_points?: LoyaltyDraft[];
  raw_text: string;
  confidence: number;
  engine: 'gemini' | 'tesseract';
  notes?: string[];
}

export interface LoyaltyPointsRow {
  points_id: number;
  store_id: number;
  store_name: string;
  label: string;
  points: number;
  expires_at: string | null;
  created_at: string;
}

/** BYOK Gemini connection status — never contains the key itself. */
export interface GeminiKeyStatus {
  connected: boolean;
  key_hint: string;
}

export interface GeminiKeyConnectResult {
  detail: string;
  connected: boolean;
  key_hint: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
