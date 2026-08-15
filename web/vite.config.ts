import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';
import { defineConfig, loadEnv, ConfigEnv } from 'vite';
import vueSetupExtend from 'vite-plugin-vue-setup-extend';
import vueJsx from '@vitejs/plugin-vue-jsx';
import { VitePWA } from 'vite-plugin-pwa';

const pathResolve = (dir: string) => {
	return resolve(__dirname, '.', dir);
};

const alias: Record<string, string> = {
	'/@': pathResolve('./src/'),
	'@views': pathResolve('./src/views'),
	'vue-i18n': 'vue-i18n/dist/vue-i18n.cjs.js',
	'@dvaformflow':pathResolve('./src/viwes/plugins/dvaadmin_form_flow/src/')
};

const viteConfig = defineConfig((mode: ConfigEnv) => {
	const env = loadEnv(mode.mode, process.cwd());
	return {
        plugins: [
            vue(),
            vueJsx(),
            vueSetupExtend(),
            VitePWA({
                registerType: 'autoUpdate',
                includeAssets: ['favicon.ico'],
                manifest: {
                    name: '换刀移动录入',
                    short_name: '换刀录入',
                    description: '盾构换刀现场移动录入',
                    theme_color: '#1f7a6d',
                    background_color: '#f4f7f8',
                    display: 'standalone',
                    start_url: '/#/mobile/tasks',
                    scope: '/',
                },
                workbox: {
                    navigateFallbackDenylist: [/^\/api\//, /^\/ws\//, /^\/media\//],
                    globPatterns: ['manifest.webmanifest', 'registerSW.js'],
                    runtimeCaching: [],
                },
            }),
        ],
		root: process.cwd(),
		resolve: { alias },
		base: mode.command === 'serve' ? './' : env.VITE_PUBLIC_PATH,
		optimizeDeps: {
			include: ['element-plus/es/locale/lang/zh-cn', 'element-plus/es/locale/lang/en', 'element-plus/es/locale/lang/zh-tw'],
		},
		cacheDir: '.vite',
		server: {
			host: '0.0.0.0',
			port: env.VITE_PORT as unknown as number,
			open: false,
			hmr: true,
			proxy: {
				'/api': {
					target: env.VITE_API_URL?.startsWith('http')
						? env.VITE_API_URL
						: `http://127.0.0.1:${env.VITE_BACKEND_PORT || 8000}`,
					changeOrigin: true,
				},
				'/ws': {
					target: (env.VITE_API_URL?.startsWith('http')
						? env.VITE_API_URL
						: `http://127.0.0.1:${env.VITE_BACKEND_PORT || 8000}`).replace(/^http/, 'ws'),
					ws: true,
					changeOrigin: true,
					configure: (proxy: any) => {
						proxy.on('error', (err: any) => {
							console.warn('[vite proxy] websocket proxy error:', err?.message || err);
						});
					},
				},
				'/gitee': {
					target: 'https://gitee.com',
					ws: true,
					changeOrigin: true,
					rewrite: (path) => path.replace(/^\/gitee/, ''),
				},
			},
		},
		build: {
			outDir: env.VITE_DIST_PATH || 'dist',
			chunkSizeWarningLimit: 1500,
			rollupOptions: {
				output: {
					entryFileNames: `assets/[name].[hash].js`,
					chunkFileNames: `assets/[name].[hash].js`,
					assetFileNames: `assets/[name].[hash].[ext]`,
					compact: true,
					manualChunks: {
						vue: ['vue', 'vue-router', 'pinia'],
						echarts: ['echarts'],
					},
				},
			},
		},
		css: { preprocessorOptions: { css: { charset: false } } },
		define: {
			__VUE_I18N_LEGACY_API__: JSON.stringify(false),
			__VUE_I18N_FULL_INSTALL__: JSON.stringify(false),
			__INTLIFY_PROD_DEVTOOLS__: JSON.stringify(false),
			__VERSION__: JSON.stringify(process.env.npm_package_version),
		},
	};
});

export default viteConfig;
