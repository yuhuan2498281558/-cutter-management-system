<template>
  <div class="project-info-card bg-white rounded-xl shadow-lg overflow-hidden transition-all duration-300 hover:shadow-2xl w-full">
    <div class="bg-gradient-to-r from-blue-600 to-indigo-600 text-white p-4">
      <h2 class="text-xl font-bold flex items-center">
        <i class="fa fa-info-circle mr-2"></i> 项目简介
        <button @click="toggleExpanded" class="ml-auto text-white/80 hover:text-white">
          <i :class="expanded ? 'fa fa-chevron-up' : 'fa fa-chevron-down'"></i>
        </button>
      </h2>
    </div>
    <div class="p-4 transition-all duration-300" :style="{ maxHeight: expanded ? 'none' : '200px', overflow: expanded ? 'visible' : 'hidden' }">
      <div class="mb-3">
        <h3 class="font-semibold text-gray-700 mb-1">项目名称</h3>
        <p class="text-gray-600">{{ projectInfo.name || '福通大桥建设项目' }}</p>
      </div>
      <div class="mb-3">
        <h3 class="font-semibold text-gray-700 mb-1">项目地址</h3>
        <p class="text-gray-600">{{ projectInfo.address || '未设置' }}</p>
      </div>
      <div class="mb-3">
        <h3 class="font-semibold text-gray-700 mb-1">建筑面积</h3>
        <p class="text-gray-600">{{ projectInfo.area || '未设置' }}</p>
      </div>
      <div class="mb-3">
        <h3 class="font-semibold text-gray-700 mb-1">项目简介</h3>
        <p class="text-gray-600">{{ projectInfo.description || '以“龙江之眼”为主题的福通大桥全长760米，起于清盛大道，终于纬一路，总投资2.6亿元，双向四车道，设计行车速度40千米/小时。其中，跨越龙江的桥体长447米，主桥两侧设置4座人行桥、2座非机动车道桥。大桥造型经抽象化设计形成桥梁的拱形结构和装饰构件，使整个造型生动形象犹如一对眨动的眼睛。大桥两侧设弧形观景平台与主拱构成龙江的“炯炯双眸”，龙江两侧设人行桥通往下部公园，连接桥上与桥下空间。' }}</p>
      </div>
      <div class="mt-4 pt-3 border-t border-gray-200">
        <div class="flex items-center text-sm text-gray-500">
          <i class="fa fa-calendar-o mr-2"></i>
          <span>更新日期: {{ projectInfo.updateDate || '2025-7-18' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, defineProps, defineEmits } from 'vue'

const props = defineProps({
  projectInfo: {
    type: Object,
    default: () => ({})
  },
  expanded: {
    type: Boolean,
    default: true
  }
})

const emits = defineEmits(['toggle'])

const expanded = ref(props.expanded)

const toggleExpanded = () => {
  expanded.value = !expanded.value
  emits('toggle', expanded.value)
}
</script>

<style scoped>
/* 可添加自定义样式 */
</style>