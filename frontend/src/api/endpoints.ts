import { api, API_BASE_URL, tokenStore } from './client';
import type {
  Category,
  LoyaltyPointsRow,
  MonthBreakdown,
  MonthlyAnalytics,
  OcrDraft,
  Paginated,
  Receipt,
  Store,
  User,
} from '../types';

export { API_BASE_URL };

export async function login(email: string, password: string) {
  const { data } = await api.post('/auth/login/', { email, password });
  tokenStore.setTokens(data.access, data.refresh);
  return data;
}

/** Email-code login: request a 6-digit code, then exchange it for JWTs. */
export async function requestLoginCode(email: string): Promise<{ detail: string; transport: string; dev_code?: string }> {
  const { data } = await api.post('/auth/login-code/', { email });
  return data;
}

export async function verifyLoginCode(
  email: string,
  code: string,
): Promise<{ access: string; refresh: string; created_account: boolean }> {
  const { data } = await api.post('/auth/verify-login-code/', { email, code });
  tokenStore.setTokens(data.access, data.refresh);
  return data;
}

/** SMS-code login: the phone-number twin of the email flow. */
export async function requestSmsCode(phone: string): Promise<{ detail: string; transport: string; dev_code?: string }> {
  const { data } = await api.post('/auth/login-code/sms/', { phone });
  return data;
}

export async function verifySmsCode(
  phone: string,
  code: string,
): Promise<{ access: string; refresh: string; created_account: boolean }> {
  const { data } = await api.post('/auth/verify-login-code/sms/', { phone, code });
  tokenStore.setTokens(data.access, data.refresh);
  return data;
}

/** WhatsApp-code login: same code model as SMS, different channel. */
export async function requestWhatsappCode(phone: string): Promise<{ detail: string; transport: string; dev_code?: string }> {
  const { data } = await api.post('/auth/login-code/whatsapp/', { phone });
  return data;
}

export async function verifyWhatsappCode(
  phone: string,
  code: string,
): Promise<{ access: string; refresh: string; created_account: boolean }> {
  const { data } = await api.post('/auth/verify-login-code/whatsapp/', { phone, code });
  tokenStore.setTokens(data.access, data.refresh);
  return data;
}

/** Public capability flags so the login page renders honest buttons. */
export async function getAuthConfig(): Promise<{ apple_enabled: boolean }> {
  const { data } = await api.get('/auth/config/');
  return data;
}

/** Sign in with Apple: exchange the identity token from the Apple JS flow
 * for SmartSpend JWTs. `name` only arrives on first consent. */
export async function appleSignIn(identityToken: string, name?: string) {
  const { data } = await api.post('/auth/apple/', {
    identity_token: identityToken,
    ...(name ? { name } : {}),
  });
  tokenStore.setTokens(data.access, data.refresh);
  return data as { created_account: boolean };
}

/** Spendable loyalty points (Smart Shopper, ClubCard, …), soonest expiry first. */
export async function listPoints(includeExpired = false): Promise<LoyaltyPointsRow[]> {
  const { data } = await api.get<Paginated<LoyaltyPointsRow>>('/points/', {
    params: includeExpired ? { include_expired: '1' } : {},
  });
  return data.results;
}

/** Digital receipts: paste the text of an e-receipt (Uber, Bolt, order
 * summaries) and get the same structured draft as a photo scan. */
export async function extractReceiptText(text: string): Promise<OcrDraft> {
  const { data } = await api.post<OcrDraft>('/receipts/extract_text/', { text });
  return data;
}

export async function register(payload: {
  email: string;
  first_name: string;
  last_name: string;
  password: string;
  monthly_budget_limit?: string;
}) {
  const { data } = await api.post<User>('/auth/register/', payload);
  return data;
}

export function logout() {
  tokenStore.clear();
}

export async function getMe() {
  const { data } = await api.get<User>('/me/');
  return data;
}

export async function updateMe(payload: Partial<User>) {
  const { data } = await api.patch<User>('/me/', payload);
  return data;
}

export async function listStores() {
  const { data } = await api.get<Paginated<Store>>('/stores/');
  return data.results;
}

export async function createStore(payload: { store_name: string; channel_type: Store['channel_type'] }) {
  const { data } = await api.post<Store>('/stores/', payload);
  return data;
}

export async function listCategories() {
  const { data } = await api.get<Paginated<Category>>('/categories/');
  return data.results;
}

export async function createCategory(payload: { category_name: string; is_essential: boolean }) {
  const { data } = await api.post<Category>('/categories/', payload);
  return data;
}

export async function listReceipts(
  params: Record<string, string> = {},
): Promise<Receipt[]> {
  const { data } = await api.get<Paginated<Receipt>>('/receipts/', { params });
  return data.results;
}

/** Authenticated CSV download of every receipt (honours the same filters). */
export async function exportReceiptsCsv(params: Record<string, string> = {}) {
  const response = await api.get('/receipts/export_csv/', { params, responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'smartspend-receipts.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

/** The backend match-or-creates stores and categories by name, so the
 * receipt draft can be posted in one shot. */
export interface ReceiptDraft {
  store?: number;
  store_name?: string;
  channel_type?: Store['channel_type'];
  purchase_date: string;
  total_amount: string;
  source_type: 'camera' | 'upload';
  verified: boolean;
  items: {
    item_name: string;
    unit_price: string | number;
    quantity: number;
    category: number | string;
    is_impulse: boolean;
  }[];
  /** Spendable points blocks read off the slip (Smart Shopper, ClubCard…). */
  loyalty_points?: { points: number; label?: string; expires_at?: string | null }[];
}

export async function createReceipt(payload: ReceiptDraft) {
  const { data } = await api.post<Receipt>('/receipts/', payload);
  return data;
}

export async function updateReceipt(id: number, payload: Partial<ReceiptDraft>) {
  const { data } = await api.patch<Receipt>(`/receipts/${id}/`, payload);
  return data;
}

export async function deleteReceipt(id: number) {
  await api.delete(`/receipts/${id}/`);
}

export async function ocrExtract(image: File) {
  const form = new FormData();
  form.append('image', image);
  const { data } = await api.post<OcrDraft>('/receipts/ocr_extract/', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function attachReceiptImage(receiptId: number, image: File) {
  const form = new FormData();
  form.append('receipt_image', image);
  const { data } = await api.patch<Receipt>(`/receipts/${receiptId}/`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function downloadMonthlyAuditPdf(year: number, month: number) {
  const response = await api.get(`/receipts/monthly_audit_pdf/`, {
    params: { year, month },
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `smartspend-audit-${year}-${String(month).padStart(2, '0')}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export async function getMonthlyAnalytics() {
  const { data } = await api.get<MonthlyAnalytics[]>('/receipts/monthly_analytics/');
  return data;
}

export async function getMonthBreakdown(year: number, month: number) {
  const { data } = await api.get<MonthBreakdown>('/receipts/month_breakdown/', {
    params: { year, month },
  });
  return data;
}
