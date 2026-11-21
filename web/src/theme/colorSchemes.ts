/**
 * 两套配色：暖白（Claude 浅色，默认）和灰白蓝（Win11 浅色）
 * 页面上的颜色由 <html data-scheme> 下的 --dv-* 变量决定（theme/tokens.scss）。
 * colors 是布局配置里跟着配色走的几项：设置抽屉会把主题色及其深浅色、顶栏和菜单颜色写成 html 的内联变量，
 * 内联变量盖过样式表，所以切换配色时这几项要一起换掉，再按新颜色重新生成内联变量（见 setings.vue 的 onColorSchemeChange）。
 * 取值与 tokens.scss 里对应的变量一致（有测试核对）。
 */
export type ColorScheme = 'claude' | 'blue';

export interface ColorSchemeColors {
	primary: string;
	topBar: string;
	topBarColor: string;
	menuBar: string;
	menuBarColor: string;
	menuBarActiveColor: string;
	columnsMenuBar: string;
	columnsMenuBarColor: string;
}

export interface ColorSchemeOption {
	value: ColorScheme;
	label: string;
	colors: ColorSchemeColors;
}

export const COLOR_SCHEMES: ColorSchemeOption[] = [
	{
		value: 'claude',
		label: '暖白',
		colors: {
			primary: '#c6613f',
			topBar: '#fffefb',
			topBarColor: '#73726c',
			menuBar: '#f9f8f3',
			menuBarColor: '#3d3d3a',
			menuBarActiveColor: '#e2dfd5',
			columnsMenuBar: '#f9f8f3',
			columnsMenuBarColor: '#3d3d3a',
		},
	},
	{
		value: 'blue',
		label: '灰白蓝',
		colors: {
			primary: '#0067c0',
			topBar: '#ffffff',
			topBarColor: '#5d5d5d',
			menuBar: '#ffffff',
			menuBarColor: '#1b1b1b',
			menuBarActiveColor: '#ebebeb',
			columnsMenuBar: '#ffffff',
			columnsMenuBarColor: '#1b1b1b',
		},
	},
];

// 缓存里没有（旧版本的配置）或不认识的值，按默认的暖白处理
export function normalizeColorScheme(value: unknown): ColorScheme {
	return value === 'blue' ? 'blue' : 'claude';
}

export function colorSchemeColors(value: unknown): ColorSchemeColors {
	const scheme = normalizeColorScheme(value);
	return (COLOR_SCHEMES.find((option) => option.value === scheme) as ColorSchemeOption).colors;
}

// 把配色写到 <html data-scheme>，tokens.scss 按它切换变量
export function applyColorScheme(value: unknown, root: HTMLElement = document.documentElement) {
	root.setAttribute('data-scheme', normalizeColorScheme(value));
}
