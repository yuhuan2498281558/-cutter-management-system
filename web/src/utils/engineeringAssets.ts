/**
 * 真实刀盘图纸和登录背景属于工程资料，不随公开仓库发布（见根目录 .gitignore）。
 * 本地及部署环境在 web/.env 中配置实际路径；未配置时使用公开占位图。
 * 通过变量绑定而非模板字面量引用，避免 Vite 在构建时把缺失文件当作模块解析。
 */
const env = import.meta.env;

export const CUTTERHEAD_IMAGE: string = env.VITE_CUTTERHEAD_IMAGE || '/cutterhead-placeholder.svg';
export const CUTTERHEAD_CLEAN_IMAGE: string = env.VITE_CUTTERHEAD_CLEAN_IMAGE || CUTTERHEAD_IMAGE;
export const LOGIN_BACKGROUND_IMAGE: string = env.VITE_LOGIN_BACKGROUND_IMAGE || '';
