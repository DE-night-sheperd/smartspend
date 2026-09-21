import { api, API_BASE_URL, tokenStore } from './client';
import type {
  Category,
  GeminiKeyConnectResult,
  GeminiKeyStatus,
  LoginAuditEntry,
  LoyaltyPointsRow,
  BudgetAdvice,
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

/** Forgot password: request a 6-digit reset code by email. The response
 * never reveals whether the address is registered. */
export async function requestPasswordReset(email: string): Promise<{ detail: string }> {
  const { data } = await api.post('/auth/password-reset/', { email });
  return data;
}

/** Check a reset code without consuming it. Fails with a message when the
 * account signs in with one-time codes instead of a password. */
export async function verifyPasswordResetCode(email: string, code: string): Promise<{ detail: string; verified: boolean }> {
  const { data } = await api.post('/auth/password-reset/verify/', { email, code });
  return data;
}

/** Set a new password using a valid reset code (consumes it). */
export async function confirmPasswordReset(email: string, code: string, newPassword: string): Promise<{ detail: string }> {
  const { data } = await api.post('/auth/password-reset/confirm/', { email, code, new_password: newPassword });
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

/** Public capability flags so the login page renders honest buttons.
 * SMS/WhatsApp tabs only appear when the backend has a real sender number. */
export async function getAuthConfig(): Promise<{
  apple_enabled: boolean;
  sms_enabled: boolean;
  whatsapp_enabled: boolean;
}> {
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

/** Manually add a points block (e.g. a balance printed on last month's slip). */
export async function createPoints(payload: {
  store_name: string;
  label?: string;
  points: number;
  expires_at?: string | null;
}): Promise<LoyaltyPointsRow> {
  const { data } = await api.post<LoyaltyPointsRow>('/points/', payload);
  return data;
}

/** Update an existing points block. */
export async function updatePoints(
  pointsId: number,
  payload: { store_name?: string; label?: string; points?: number; expires_at?: string | null },
): Promise<LoyaltyPointsRow> {
  const { data } = await api.patch<LoyaltyPointsRow>(`/points/${pointsId}/`, payload);
  return data;
}

/** Delete a points block (e.g. after spending it in-store). */
export async function deletePoints(pointsId: number): Promise<void> {
  await api.delete(`/points/${pointsId}/`);
}

/** Change password (requires the current one). */
export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await api.post('/me/password/', { old_password: oldPassword, new_password: newPassword });
}

/** Digital receipts: paste the text of an e-receipt (Uber, Bolt, order
 * summaries) and get the same structured draft as a photo scan. */
export async function extractReceiptText(text: string): Promise<OcrDraft> {
  const { data } = await api.post<OcrDraft>('/receipts/extract_text/', { text });
  return data;
}

// --- Bring-your-own Gemini key (BYOK) --------------------------------------
// Google has no OAuth flow that mints Gemini keys for third-party apps, so
// the user creates their free key at AI Studio and pastes it once; scans
// then use their own key/quota. Keys are stored encrypted server-side and
// are never returned to the client.

// --- Sign-in audit trail ----------------------------------------------------
// Every successful sign-in (password, email/SMS/WhatsApp code, Apple) is
// recorded server-side; this serves the newest entries plus the totals.

export async function getLoginAudit(): Promise<LoginAuditEntry[]> {
  const { data } = await api.get<LoginAuditEntry[]>('/me/logins/');
  return data;
}

export async function getGeminiKeyStatus(): Promise<GeminiKeyStatus> {
  const { data } = await api.get<GeminiKeyStatus>('/me/gemini-key/');
  return data;
}

export async function connectGeminiKey(apiKey: string): Promise<GeminiKeyConnectResult> {
  const { data } = await api.post<GeminiKeyConnectResult>('/me/gemini-key/connect/', { api_key: apiKey });
  return data;
}

export async function disconnectGeminiKey(): Promise<{ connected: boolean }> {
  const { data } = await api.post<{ connected: boolean }>('/me/gemini-key/disconnect/');
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
): Promise<{ results: Receipt[]; count: number }> {
  // `limit` is a client-side page-size hint: strip it from the request and
  // slice locally so the API stays untouched (it already pages at 25).
  const { limit, ...rest } = params;
  const { data } = await api.get<Paginated<Receipt>>('/receipts/', { params: rest });
  const n = limit ? parseInt(limit, 10) : NaN;
  const results = Number.isFinite(n) && n > 0 ? data.results.slice(0, n) : data.results;
  return { results, count: data.count };
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

/** Automated "cut X to save Y" suggestions for one month, computed from
 * the user's own receipts (categories, impulse flags, pacing, stores). */
export async function getBudgetAdvice(year: number, month: number) {
  const { data } = await api.get<BudgetAdvice>('/receipts/budget_advice/', {
    params: { year, month },
  });
  return data;
}

export async function getMonthBreakdown(year: number, month: number) {
  const { data } = await api.get<MonthBreakdown>('/receipts/month_breakdown/', {
    params: { year, month },
  });
  return data;
}
