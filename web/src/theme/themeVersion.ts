// 主题版本号。全站配色换版时改这个值：旧的布局配置缓存里存着旧颜色，
// 其中 themeConfigStyle 会整串写进 html 的内联样式，盖掉样式表里的新变量。
export const THEME_VERSION = 'a-2026-10';

interface ThemeCacheStorage {
	get(key: string): any;
	set(key: string, val: any): void;
	remove(key: string): void;
}

// 缓存的主题版本与当前不一致时，删除两份主题缓存并记下当前版本，之后照常使用默认配置。
// 返回是否清理过。
export function resetStaleThemeCache(storage: ThemeCacheStorage): boolean {
	if (storage.get('themeVersion') === THEME_VERSION) return false;
	storage.remove('themeConfig');
	storage.remove('themeConfigStyle');
	storage.set('themeVersion', THEME_VERSION);
	return true;
}
