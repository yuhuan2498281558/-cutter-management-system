<template>
  <section class="stratum-comparison">
    <div class="comparison-heading">
      <div><h3>岩层下的厂家刀具表现</h3><p>按完整服役环段的正占比岩层分组；历史工程地质条件不作为岩性分组，缺占比不回退。厂家归属原安装刀具。</p></div>
      <el-select v-model="selectedStratum" clearable filterable placeholder="全部经历地层" aria-label="选择服役地层" :disabled="loading && !options.length">
        <el-option v-for="option in options" :key="option.value" :value="option.value" :label="option.label" />
      </el-select>
    </div>
    <ChartCard title="地层与厂家对照" chart-height="auto" :loading="loading" :error="error" :is-empty="!data?.items.length" @retry="load"
      empty-description="当前范围没有该地层下可确认的刀具服役样本。">
      <el-table :data="data?.items || []" border size="small" max-height="460">
        <el-table-column prop="stratum_name" label="服役地层" min-width="155" fixed />
        <el-table-column prop="manufacturer" label="原安装厂家" min-width="145" />
        <el-table-column prop="sample_count" label="闭合服役段" width="105" align="right" />
        <el-table-column label="整段平均服役环数" min-width="145" align="right"><template #default="{ row }">{{ formatNumber(row.avg_service_rings, 1) }} 环</template></el-table-column>
        <el-table-column label="该地层平均等效环数" min-width="170" align="right"><template #default="{ row }">{{ row.avg_equivalent_rings == null ? '占比不完整' : `${formatNumber(row.avg_equivalent_rings, 2)} 环` }}<small>完整占比样本 {{ row.complete_ratio_sample_count }}</small></template></el-table-column>
        <el-table-column label="原安装均价" min-width="130" align="right"><template #default="{ row }">{{ formatCurrency(row.avg_installation_price) }}<small>有价样本 {{ row.priced_count }}</small></template></el-table-column>
        <el-table-column label="非正常磨损比例" min-width="150" align="right"><template #default="{ row }">{{ formatPercent(row.abnormal_rate) }}<small>{{ row.abnormal_count }} / {{ row.wear_recorded_count }} 条有记录</small></template></el-table-column>
        <el-table-column label="缺占比环数" prop="missing_ratio_rings" width="110" align="right" />
      </el-table>
      <p class="comparison-note">{{ data?.basis }}</p>
      <p class="comparison-note">{{ data?.ratio_basis }}</p>
      <p class="comparison-note">地层是整段服役背景，磨损为拆除时观察结果；多地层服役不能据此认定某一种地层造成磨损。整段平均服役环数包含其他地层。</p>
    </ChartCard>
    <p v-if="data" class="comparison-note">配对待核对 {{ data.unpaired_count }} 段；缺地层 {{ data.missing_stratum_segment_count }} 段；原厂家未记录 {{ data.unknown_manufacturer_count }} 段。继承项目、机器、拆除环段和刀型条件；上方开仓地层筛选不代替完整服役段地层。</p>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import ChartCard from './ChartCard.vue';
import { getBrandStratumPerformance } from '../api';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { formatCurrency, formatNumber, formatPercent, requireAnalysisV2 } from '../utils/presentation';
import type { AnalysisFilter, AnalysisMeta } from '../types';

interface Item {
  stratum_code: string; stratum_name: string; manufacturer: string; sample_count: number;
  avg_service_rings: number; avg_equivalent_rings: number | null; complete_ratio_sample_count: number;
  avg_installation_price: number | null; priced_count: number; abnormal_rate: number | null;
  abnormal_count: number; wear_recorded_count: number; missing_ratio_rings: number;
}
interface Result {
  meta: AnalysisMeta; items: Item[]; stratum_options: { value: string; label: string }[];
  basis: string; ratio_basis: string; unpaired_count: number; missing_stratum_segment_count: number; unknown_manufacturer_count: number;
}
const props = defineProps<{ filter: AnalysisFilter }>();
const selectedStratum = ref('');
const options = ref<Result['stratum_options']>([]);
watch(() => props.filter, () => { selectedStratum.value = ''; options.value = []; }, { deep: true, flush: 'sync' });
const { data, loading, error, load } = useAnalysisQuery<Result>(
  () => ({ ...props.filter, service_stratum: selectedStratum.value }),
  async filter => {
    const result = requireAnalysisV2<Result>((await getBrandStratumPerformance(filter)).data);
    if (!Array.isArray(result.items) || !Array.isArray(result.stratum_options)) throw new Error('地层厂家分析数据格式不完整，请重新加载。');
    return result;
  },
);
watch(data, result => { if (result) options.value = result.stratum_options; });
</script>

<style scoped lang="scss">
.stratum-comparison { margin: 20px 0; }
.comparison-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 12px; }
h3 { font-size: 17px; margin: 0 0 5px; }
.comparison-heading p, .comparison-note { font-size: 13px; line-height: 1.65; color: var(--el-text-color-regular); margin: 6px 0; }
.comparison-heading .el-select { width: 260px; flex-shrink: 0; }
small { display: block; font-size: 12px; color: var(--el-text-color-secondary); margin-top: 4px; }
@media (max-width: 700px) { .comparison-heading { align-items: stretch; flex-direction: column; } .comparison-heading .el-select { width: 100%; } }
</style>
