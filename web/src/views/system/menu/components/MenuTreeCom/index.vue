<template>
	<TreePanel
		ref="panelRef"
		placeholder="请输入菜单名称"
		title="菜单列表"
		:icon="Menu"
		tip="1.红色菜单代表状态禁用; 2.添加菜单，如果是目录，组件地址为空即可; 3.添加根节点菜单，父级ID为空即可; 4.支持拖拽菜单;"
		:data="treeData"
		:props="defaultTreeProps"
		:filter-node-method="filterNode"
		:load="handleTreeLoad"
		lazy
		@node-click="handleNodeClick"
	>
		<template #node="{ node, data }">
			<SvgIcon :name="node.data.icon" :color="data.status ? 'var(--el-color-primary)' : undefined" :class="{ 'menu-tree-disabled': !data.status }" />
			<span :class="{ 'menu-tree-disabled': !data.status }">{{ node.label }}</span>
		</template>

		<template #footer>
			<el-tooltip effect="dark" content="新增">
				<el-icon size="16" v-auth="'menu:Create'" @click="handleUpdateMenu('create')">
					<Plus />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="编辑">
				<el-icon size="16" v-auth="'menu:Update'" @click="handleUpdateMenu('update')">
					<Edit />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="上移">
				<el-icon size="16" v-auth="'menu:MoveUp'" @click="handleSort('up')">
					<Top />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="下移">
				<el-icon size="16" v-auth="'menu:MoveDown'" @click="handleSort('down')">
					<Bottom />
				</el-icon>
			</el-tooltip>

			<el-tooltip effect="dark" content="删除">
				<el-icon size="16" v-auth="'menu:Delete'" @click="handleDeleteMenu()">
					<Delete />
				</el-icon>
			</el-tooltip>
		</template>
	</TreePanel>
</template>

<script lang="ts" setup>
import { ref, toRaw, computed } from 'vue';
import { Menu, Plus, Edit, Top, Bottom, Delete } from '@element-plus/icons-vue';
import SvgIcon from '/@/components/svgIcon/index.vue';
import TreePanel from '/@/components/TreePanel.vue';
import { lazyLoadMenu, menuMoveUp, menuMoveDown } from '../../api';
import { warningNotification } from '/@/utils/message';
import { TreeTypes, MenuTreeItemType } from '../../types';
import type Node from 'element-plus/es/components/tree/src/model/node';

interface IProps {
	treeData: TreeTypes[];
}

const defaultTreeProps: any = {
	children: 'children',
	label: 'name',
	icon: 'icon',
	isLeaf: (data: TreeTypes[], node: Node) => {
		if (node.data.is_catalog) {
			return false;
		} else {
			return true;
		}
	},
};

const panelRef = ref<InstanceType<typeof TreePanel>>();
// 父页面通过 treeRef 读取当前选中节点（编辑时取上级菜单）
const treeRef = computed(() => panelRef.value?.treeRef);

withDefaults(defineProps<IProps>(), {
	treeData: () => [],
});
const emit = defineEmits(['treeClick', 'deleteDept', 'updateDept']);

let sortDisable = ref(false);
let treeSelectMenu = ref<Partial<MenuTreeItemType>>({});
let treeSelectNode = ref<Node | null>(null);

/**
 * 树的搜索事件
 */
const filterNode = (value: string, data: any) => {
	if (!value) return true;
	return toRaw(data).name.indexOf(value) !== -1;
};

/**
 * 树的懒加载
 */
const handleTreeLoad = (node: Node, resolve: Function) => {
	if (node.level !== 0) {
		lazyLoadMenu({ parent: node.data.id }).then((res: APIResponseData) => {
			resolve(res.data);
		});
	}
};

/**
 * 树的点击事件
 */
const handleNodeClick = (record: MenuTreeItemType, node: Node) => {
	treeSelectMenu.value = record;
	treeSelectNode.value = node;
	emit('treeClick', record);
};

/**
 * 点击左侧编辑按钮
 */
const handleUpdateMenu = (type: string) => {
	if (type === 'update') {
		if (!treeSelectMenu.value.id) {
			warningNotification('请选择菜单！');
			return;
		}
		emit('updateDept', type, treeSelectMenu.value);
	} else {
		emit('updateDept', type);
	}
};

/**
 * 删除菜单
 */
const handleDeleteMenu = () => {
	if (!treeSelectMenu.value.id) {
		warningNotification('请选择菜单！');
		return;
	}
	emit('deleteDept', treeSelectMenu.value.id, () => {
		treeSelectMenu.value = {};
	});
};

/**
 * 移动操作
 */
const handleSort = async (type: string) => {
	if (!treeSelectMenu.value.id) {
		warningNotification('请选择菜单！');
		return;
	}
	if (sortDisable.value) return;

	const parentList = treeSelectNode.value?.parent.childNodes || [];
	const index = parentList.findIndex((i) => i.data.id === treeSelectMenu.value.id);
	const record = parentList.find((i) => i.data.id === treeSelectMenu.value.id);

	if (type === 'up') {
		if (index === 0) return;
		parentList.splice(index - 1, 0, record as any);
		parentList.splice(index + 1, 1);
		sortDisable.value = true;
		await menuMoveUp({ menu_id: treeSelectMenu.value.id });
		sortDisable.value = false;
	}
	if (type === 'down') {
		parentList.splice(index + 2, 0, record as any);
		parentList.splice(index, 1);
		sortDisable.value = true;
		await menuMoveDown({ menu_id: treeSelectMenu.value.id });
		sortDisable.value = false;
	}
};

defineExpose({
	treeRef,
});
</script>

<style lang="scss" scoped>
// 禁用的菜单标红（标题旁 ⓘ 里的说明 1）
.menu-tree-disabled {
	color: var(--dv-danger);
}
</style>
