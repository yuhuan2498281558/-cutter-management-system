import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import { directive } from '/@/directive/index';
import { i18n } from '/@/i18n';
import other from '/@/utils/other';
import '/@/assets/style/tailwind.css'; // 先引入tailwind css, 以免element-plus冲突
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import Vant from 'vant';
import 'vant/lib/index.css';
import '/@/theme/index.scss';
import mitt from 'mitt';
import VueGridLayout from 'vue-grid-layout';
import piniaPersist from 'pinia-plugin-persist';
// @ts-ignore
import fastCrud from './settings.ts';
import pinia from './stores';
import {RegisterPermission} from '/@/plugin/permission/index';
// @ts-ignore
import eIconPicker, { iconList, analyzingIconForIconfont } from 'e-icon-picker';
import 'e-icon-picker/icon/default-icon/symbol.js'; //基本彩色图标库
import 'e-icon-picker/index.css'; // 基本样式，包含基本图标
import 'font-awesome/css/font-awesome.min.css';
import elementPlus from 'e-icon-picker/icon/ele/element-plus.js'; //element-plus的图标
import fontAwesome470 from 'e-icon-picker/icon/fontawesome/font-awesome.v4.7.0.js'; //fontAwesome470的图标
import eIconList from 'e-icon-picker/icon/default-icon/eIconList.js';
import iconfont from '/@/assets/iconfont/iconfont.json'; //引入json文件
import '/@/assets/iconfont/iconfont.css'; //引入css
// 自动注册插件
import { scanAndInstallPlugins } from '/@/views/plugins/index';
import VXETable from 'vxe-table'
import 'vxe-table/lib/style.css'

import '/@/assets/style/reset.scss';
import 'element-tree-line/dist/style.css'

let forIconfont = analyzingIconForIconfont(iconfont); //解析class
iconList.addIcon(forIconfont.list); // 添加iconfont dvadmin3的icon
iconList.addIcon(elementPlus); // 添加element plus的图标
iconList.addIcon(fontAwesome470); // 添加fontAwesome 470版本的图标

let app = createApp(App);

scanAndInstallPlugins(app);

app.use(eIconPicker, {
	addIconList: eIconList, //全局添加图标
	removeIconList: [], //全局删除图标
	zIndex: 3100, //选择器弹层的最低层,全局配置
});

pinia.use(piniaPersist);
directive(app);
other.elSvg(app);


app.use(VXETable)
app.use(pinia).use(router).use(ElementPlus, { i18n: i18n.global.t }).use(Vant).use(i18n).use(VueGridLayout).use(fastCrud).mount('#app');

app.config.globalProperties.mittBus = mitt();

// 注释编号:django-vue3-admin__main472414:代码开始行
// 功能说明:取消Dialog被触发关闭的功能
app._context.components.ElDialog.props.closeOnClickModal.default = false   //配置elmentplus之Dialog点击遮罩层点击不关闭
app._context.components.ElDialog.props.closeOnPressEscape.default = false;  //配置elmentplus之Dialog按Esc健不关闭
// 注释编号:django-vue3-admin__main472414:代码结束行

// 注释编号:workspace.json__main552310:导入字段只读的配置效果就是，在添加和编辑时都看不到这个字段，而查看可以看到该字段
import { readonlyRegisterMergeColumnPlugin } from "/@/custom/readOnyMethod";
readonlyRegisterMergeColumnPlugin();  //导入之后执行

// 注释编号:django-vue3-admin__main292016:导入自定义字段类型IP地址字段ipInputFieldTyps并执行进行全局暴露
import {ipInputFieldTyps} from "/@/custom/ipInputFieldType"
ipInputFieldTyps();


// 注释编号:django-vue3-admin__main071411:导入对日期类型type的特殊处理
import { customDateRegisterMergeColumnPlugin } from "/@/custom/customDate";
customDateRegisterMergeColumnPlugin();  //导入之后执行

// 注释编号:django-vue3-admin__main220812:导入全局的columns的配置
import { columnRegisterMergeColumnPlugin } from "/@/custom/customColumns";
columnRegisterMergeColumnPlugin();  //导入之后执行
