import axios from 'axios';
import { Session } from '/@/utils/storage';

// 创建专用的axios实例，不使用全局拦截器
const aiService = axios.create({
	baseURL: import.meta.env.VITE_API_URL || '',
	timeout: 50000,
	headers: { 'Content-Type': 'application/json' },
});

const apiBaseURL = String(import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

function buildApiUrl(path: string) {
	if (!apiBaseURL || apiBaseURL === '/') return path;
	return `${apiBaseURL}${path}`;
}

function unwrapResponse(response: { data: any }) {
	if (response.data?.code !== 2000) {
		throw new Error(response.data?.msg || '服务返回了无效响应');
	}
	return response.data;
}

// 添加请求拦截器（只添加token）
aiService.interceptors.request.use(
	(config) => {
		const token = Session.get('token');
		if (token) {
			// 添加JWT前缀
			config.headers['Authorization'] = `JWT ${token}`;
		}
		return config;
	},
	(error) => {
		return Promise.reject(error);
	}
);

export interface ChatStreamCallbacks {
	onChunk: (text: string) => void;
	onDone: () => void;
	onError: (msg: string) => void;
	onMemory?: (info: any) => void;
	onAnswer?: (text: string) => void;
}

/**
 * AI助手API接口
 */
export function useAiAssistantApi() {
	return {
		// 发送消息（普通）
		chat: (data: { query: string; project_id?: string; ring_range?: number[]; route_mode?: 'rule' | 'agent' }) => {
			return aiService.post('/api/ai/chat/', data).then(unwrapResponse);
		},
		// 流式发送消息，逐 token 回调
		chatStream: async (
			data: { query: string; project_id?: string; ring_range?: number[]; route_mode?: 'rule' | 'agent' },
			callbacks: ChatStreamCallbacks,
			signal?: AbortSignal
		) => {
			const token = Session.get('token');
			let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
			let finished = false;
			try {
				const res = await fetch(buildApiUrl('/api/ai/chat/stream/'), {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
						'Accept': 'text/event-stream',
						...(token ? { Authorization: `JWT ${token}` } : {}),
					},
					body: JSON.stringify(data),
					signal,
				});
				if (!res.ok) {
					throw new Error(`请求失败：${res.status}`);
				}
				if (res.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'text/event-stream') {
					throw new Error('服务未返回流式响应，请重试');
				}
				if (!res.body) {
					throw new Error('响应体为空');
				}
				reader = res.body.getReader();
				const decoder = new TextDecoder('utf-8');
				let buf = '';
				let eventData: string[] = [];
				const dispatchEvent = () => {
					if (!eventData.length || finished || signal?.aborted) return;
					let evt;
					try {
						evt = JSON.parse(eventData.join('\n'));
					} catch {
						throw new Error('流式响应解析失败，回答可能不完整');
					}
					eventData = [];
					if (!evt || typeof evt.type !== 'string') throw new Error('流式事件格式无效');
					if (evt.type === 'chunk') {
						if (typeof evt.content !== 'string') throw new Error('流式文本格式无效');
						callbacks.onChunk(evt.content);
					} else if (evt.type === 'answer') {
						if (typeof evt.content !== 'string' || !evt.content.trim()) throw new Error('最终回答格式无效');
						callbacks.onAnswer?.(evt.content);
					} else if (evt.type === 'memory') {
						// 后端把诊断字段平铺在事件对象上，且槽位字段名为 slot_names。
						callbacks.onMemory?.(evt.memory || evt.content || {
							backend: evt.backend,
							message_count: evt.message_count,
							summary_revision: evt.summary_revision,
							slots: evt.slot_names,
						});
					} else if (evt.type === 'done') {
						finished = true;
						callbacks.onDone();
					} else if (evt.type === 'error') {
						finished = true;
						callbacks.onError(evt.content || '流式响应出错');
					}
				};
				const handleLine = (rawLine: string) => {
					const line = rawLine.replace(/\r$/, '');
					if (!line) dispatchEvent();
					else if (line.startsWith('data:')) eventData.push(line.slice(5).replace(/^ /, ''));
				};
				while (!finished && !signal?.aborted) {
					const { done, value } = await reader.read();
					if (done) break;
					if (signal?.aborted) break;
					buf += decoder.decode(value, { stream: true });
					const lines = buf.split('\n');
					buf = lines.pop() ?? '';
					for (const line of lines) {
						if (finished || signal?.aborted) break;
						handleLine(line);
					}
				}
				if (!finished && !signal?.aborted) {
					buf += decoder.decode();
					if (buf) handleLine(buf);
					dispatchEvent();
					if (!finished) throw new Error('连接提前结束，回答不完整，请重试');
				}
			} catch (err: any) {
				if (!finished && !signal?.aborted && err.name !== 'AbortError') {
					finished = true;
					callbacks.onError(err.message || '网络错误');
				}
			} finally {
				if (reader) {
					try { await reader.cancel(); } catch { /* 连接可能已经关闭。 */ }
					reader.releaseLock();
				}
			}
		},
		// 健康检查
		health: () => {
			return aiService.get('/api/ai/health/').then(unwrapResponse);
		},
		// 获取记忆中的历史对话（只读，用于刷新后回填）
		history: (params?: { before_sequence?: number; limit?: number }) => {
			return aiService.get('/api/ai/history/', { params }).then(unwrapResponse);
		},
		// 重置对话
		reset: () => {
			return aiService.post('/api/ai/reset/').then(unwrapResponse);
		},
	};
}
