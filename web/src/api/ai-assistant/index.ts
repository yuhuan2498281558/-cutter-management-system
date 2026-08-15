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
}

/**
 * AI助手API接口
 */
export function useAiAssistantApi() {
	return {
		// 发送消息（普通）
		chat: (data: { query: string; project_id?: string; ring_range?: number[]; route_mode?: 'rule' | 'agent' }) => {
			return aiService.post('/api/ai/chat/', data).then(res => res.data);
		},
		// 流式发送消息，逐 token 回调
		chatStream: (
			data: { query: string; project_id?: string; ring_range?: number[]; route_mode?: 'rule' | 'agent' },
			callbacks: ChatStreamCallbacks,
			signal?: AbortSignal
		) => {
			const token = Session.get('token');
			return fetch(buildApiUrl('/api/ai/chat/stream/'), {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Accept': 'text/event-stream',
					...(token ? { Authorization: `JWT ${token}` } : {}),
				},
				body: JSON.stringify(data),
				signal,
			}).then(async (res) => {
				if (!res.ok) {
					callbacks.onError(`请求失败：${res.status}`);
					return;
				}
				if (!res.body) {
					callbacks.onError('响应体为空');
					return;
				}
				const reader = res.body.getReader();
				const decoder = new TextDecoder('utf-8');
				let buf = '';
				let finished = false;
				const handleLine = (rawLine: string) => {
					const line = rawLine.trimEnd();
					if (!line.startsWith('data:')) return;
					try {
						const evt = JSON.parse(line.slice(5).trimStart());
						if (evt.type === 'chunk') callbacks.onChunk(evt.content || '');
						else if (evt.type === 'done') {
							finished = true;
							callbacks.onDone();
						}
						else if (evt.type === 'error') {
							finished = true;
							callbacks.onError(evt.content || '流式响应出错');
						}
					} catch {}
				};
				while (true) {
					const { done, value } = await reader.read();
					if (done) break;
					buf += decoder.decode(value, { stream: true });
					const lines = buf.split('\n');
					buf = lines.pop() ?? '';
					for (const line of lines) handleLine(line);
				}
				if (buf) handleLine(buf);
				if (!finished) callbacks.onDone();
			}).catch((err) => {
				if (err.name !== 'AbortError') callbacks.onError(err.message || '网络错误');
			});
		},
		// 健康检查
		health: () => {
			return aiService.get('/api/ai/health/').then(res => res.data);
		},
		// 重置对话
		reset: () => {
			return aiService.post('/api/ai/reset/').then(res => res.data);
		},
	};
}
