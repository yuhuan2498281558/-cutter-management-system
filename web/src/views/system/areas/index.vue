<template>
	<fs-page class="PageFeatureSearchMulti">
		<fs-crud ref="crudRef" v-bind="crudBinding">
			<template #cell_url="scope">
				<el-tag size="small">{{ scope.row.url }}</el-tag>
			</template>
		</fs-crud>
	</fs-page>
</template>

<script lang="ts">
import { ref, onMounted, defineComponent} from 'vue';
import { useFs } from '@fast-crud/fast-crud';
import createCrudOptions  from './crud';


export default defineComponent({    //这里配置defineComponent
    name: "CrudDemoModelViewSet",   //把name放在这里进行配置了
    setup() {   //这里配置了setup()

		const { crudBinding, crudRef, crudExpose, resetCrudOptions } = useFs({ createCrudOptions});


		// 页面打开后获取列表数据
		onMounted(() => {
			crudExpose.doRefresh();
		});
		return {
		//增加了return把需要给上面<template>内调用的<fs-crud ref="crudRef" v-bind="crudBinding">
				crudBinding,
				crudRef,

			};
    } 	//这里关闭setup()
  });  //关闭defineComponent

 </script>