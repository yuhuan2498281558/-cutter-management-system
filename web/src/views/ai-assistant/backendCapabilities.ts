// 旧云端后端不处理 focus_sources；模板筛选仍可在前端使用。
export const supportsFocusSources = import.meta.env.VITE_AI_FOCUS_SOURCES !== 'false';
