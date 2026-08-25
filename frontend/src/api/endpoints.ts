import { api, tokenStore } from './client';
import type {
  Category,
  MonthlyAnalytics,
  Paginated,
  Receipt,
  Store,
  User,
} from '../types';

export async function login(email: string, password: string) {
  const { data } = await api.post('/auth/login/', { email, password });
  tokenStore.setTokens(data.access, data.refresh);
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

export async function listReceipts() {
  const { data } = await api.get<Paginated<Receipt>>('/receipts/');
  return data.results;
}

export async function createReceipt(payload: Omit<Receipt, 'receipt_id' | 'user' | 'created_at' | 'store_name'>) {
  const { data } = await api.post<Receipt>('/receipts/', payload);
  return data;
}

export async function updateReceipt(id: number, payload: Partial<Receipt>) {
  const { data } = await api.patch<Receipt>(`/receipts/${id}/`, payload);
  return data;
}

export async function deleteReceipt(id: number) {
  await api.delete(`/receipts/${id}/`);
}

export async function getMonthlyAnalytics() {
  const { data } = await api.get<MonthlyAnalytics[]>('/receipts/monthly_analytics/');
  return data;
}
