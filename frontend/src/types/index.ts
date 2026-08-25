export interface User {
  user_id: string;
  email: string;
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
  category: number;
  category_name?: string;
  item_name: string;
  unit_price: string;
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
  verified: boolean;
  created_at: string;
  items: ReceiptItem[];
}

export interface MonthlyAnalytics {
  audit_month: string;
  total_spent: string;
  impulse_spend: string;
  monthly_budget_limit: string;
  budget_variance: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
