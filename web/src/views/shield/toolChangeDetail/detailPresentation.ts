import type { ExportColumn, ExportMetaItem } from '../utils/export';

export const TOOL_PARENT_TYPE_LABELS: any = {
  'DISC': '滚刀',
  'RIPPER': '撕裂刀',
  'SCRAPER': '刮刀',
};

// 展示刀位检查状态。
export const checkStatus = (row: any) => {
  if (!row?.is_checked) return '尚未检查';
  return row.is_replaced ? '已换刀' : '已检查未换';
};

// 汇总新刀配件信息。
export const newToolSummary = (row: any) => {
  const record = row?.new_tool_record_data;
  if (!record) return '-';
  if (row.tool_parent_type === 'SCRAPER') {
    return record.scraper_manufacturer ? `厂家：${record.scraper_manufacturer}` : '-';
  }
  return [
    record.ring_type_display || record.ring_type ? `刀圈：${record.ring_type_display || record.ring_type} / ${record.ring_manufacturer || '-'}` : '',
    record.shaft_condition_display || record.shaft_condition ? `刀轴：${record.shaft_condition_display || record.shaft_condition} / ${record.shaft_manufacturer || '-'}` : '',
    record.hub_condition_display || record.hub_condition ? `刀毂：${record.hub_condition_display || record.hub_condition} / ${record.hub_manufacturer || '-'}` : '',
  ].filter(Boolean).join('\n') || '-';
};

export const DETAIL_EXPORT_COLUMNS: ExportColumn[] = [
  { key: 'tool_parent_type_display', title: '刀具父类型', printWidth: 14 },
  { key: 'tool_type_name', title: '刀具类型名称', printWidth: 36 },
  { key: 'cutter_position_no', title: '刀位号', printWidth: 12 },
  { key: 'is_checked', title: '检查状态', printWidth: 18, formatter: (row) => checkStatus(row) },
  { key: 'tool_number', title: '刀具编号', printWidth: 23 },
  { key: 'wear_condition', title: '磨损情况', printWidth: 15 },
  { key: 'blade_wear_amount', title: '刀刃磨损量', printWidth: 16 },
  { key: 'trajectory', title: '刀位轨迹', printWidth: 18, formatter: (row) => row.trajectory?.display || '待按最终图纸核对' },
  { key: 'is_replaced', title: '是否更换', printWidth: 12, formatter: (row) => row.is_replaced ? '是' : '否' },
  { key: 'replacement_count', title: '累计更换次数', printWidth: 17 },
  { key: 'manufacturer', title: '厂家', printWidth: 26 },
  { key: 'new_tool_record_data', title: '新刀信息', printWidth: 48, formatter: (row) => newToolSummary(row) },
  { key: 'replacement_type', title: '更换类型', printWidth: 17, formatter: (row) => row.replacement_type === 'COMPLETE' ? '整刀更换' : row.replacement_type === 'REPAIR' ? '维修' : '' },
  { key: 'repair_parts', title: '维修部位', printWidth: 18 },
  { key: 'brand', title: '品牌', printWidth: 18 },
  { key: 'price', title: '价格', printWidth: 14 },
  { key: 'old_photo_links', title: '旧刀照片链接', printWidth: 32, formatter: (row) => (row.old_photo_links || []).map((item: any) => `${item.name || '照片'}：${item.url}`).join('\n') },
  { key: 'remark', title: '备注', printWidth: 32 },
];

// 将空值显示为占位符。
export const formatEmpty = (value: any) => value !== null && value !== undefined && value !== '' ? value : '-';

// 按换刀环号生成导出文件名。
export const buildExportFilename = (ringNo: any) => {
  return ringNo ? `换刀明细记录-第${ringNo}环` : '换刀明细记录';
};

// 组装开仓信息导出元数据。
export const buildExportMeta = (info: any, stratumText: string): ExportMetaItem[] => {
  return [
    { label: '换刀环号', value: formatEmpty(info.ring_no) },
    { label: '项目', value: formatEmpty(info.project_name) },
    { label: '开仓时间', value: formatEmpty(info.open_time) },
    { label: '区间', value: formatEmpty(info.section) },
    { label: '盾构机编号', value: formatEmpty(info.shield_model_name) },
    { label: '开仓编号', value: formatEmpty(info.warehouse_id) },
    { label: '换刀日期', value: formatEmpty(info.tool_change_date) },
    { label: '上次换刀环号', value: formatEmpty(info.last_ring_no) },
    { label: '期间掘进环数（环）', value: formatEmpty(info.rings_between_openings) },
    { label: '开仓持续时间（小时）', value: formatEmpty(info.opening_duration) },
    { label: '换刀总时长（小时）', value: formatEmpty(info.tool_change_duration) },
    { label: '检查刀具数量（把）', value: formatEmpty(info.checked_tool_count) },
    { label: '更换刀具数量（把）', value: formatEmpty(info.replaced_tool_count) },
    { label: '本次使用距离（m）', value: formatEmpty(info.usage_distance) },
    { label: '两次开仓间地层信息', value: stratumText, span: 3 },
    { label: '开仓位置地层信息', value: formatEmpty(info.geological_conditions), span: 3 },
  ];
};

// 格式化两次开仓间的地层信息。
export const formatStratumBetween = (list: any) => {
  if (!list || !Array.isArray(list) || list.length === 0) {
    return '-';
  }

  try {
    // 检查是否是对象数组格式
    if (typeof list[0] === 'object' && list[0] !== null) {
      return list.map((item: any) => {
        const name = item.stratum_type_name || item.name || '未知地层';
        const count = item.ring_count || item.count || 0;
        return `${name}(${count}环)`;
      }).join('、');
    }
    // 如果是其他格式，直接返回
    return String(list);
  } catch (error) {
    console.error('格式化地层信息失败:', error);
    return '-';
  }
};

// 按数字和文本片段自然排序刀位号。
export const naturalSort = (a: string, b: string) => {
  const regex = /(\d+)|(\D+)/g;
  const aParts = a.match(regex) || [];
  const bParts = b.match(regex) || [];

  for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
    const aPart = aParts[i] || '';
    const bPart = bParts[i] || '';
    const aNum = parseInt(aPart);
    const bNum = parseInt(bPart);

    if (!isNaN(aNum) && !isNaN(bNum)) {
      if (aNum !== bNum) return aNum - bNum;
    } else {
      if (aPart !== bPart) return aPart.localeCompare(bPart);
    }
  }
  return 0;
};

// 合并刀位和已保存明细并按刀位号排序。
export const buildDetailRows = (cutterPositions: any[], existingDetails: any[]) => {
  const detailMap = new Map();
  existingDetails.forEach((d: any) => {
    detailMap.set(d.cutter_position_no, d);
  });

  // 构建表格数据
  return cutterPositions.map((pos: any) => {
    const existingDetail = detailMap.get(pos.cutter_position_no);

    // 获取刀具类型名称（后端序列化器已经将 tool_info.tool_type_name 提升到顶层）
    const toolTypeName = pos.tool_type_name || '-';

    // 转换价格为数字类型
    let price = existingDetail?.price;
    if (price !== null && price !== undefined) {
      price = typeof price === 'string' ? parseFloat(price) : price;
    }

    // 只展示后端保存的编号，缺失时保留空值。
    const toolNumber = existingDetail?.tool_number || '';

    return {
      id: existingDetail?.id,
      cutter_position_id: pos.id,
      cutter_position_no: pos.cutter_position_no,
      tool_parent_type: pos.tool_type,
      tool_parent_type_display: TOOL_PARENT_TYPE_LABELS[pos.tool_type] || pos.tool_type,
      tool_type_name: toolTypeName,
      tool_number: toolNumber,
      is_checked: existingDetail?.is_checked || false,
      check_result: existingDetail?.check_result || 'PENDING',
      wear_condition: existingDetail?.wear_condition || '',
      blade_wear_amount: existingDetail?.blade_wear_amount ?? null,
      trajectory: existingDetail?.trajectory || null,
      is_replaced: existingDetail?.is_replaced || false,
      replacement_count: existingDetail?.replacement_count || 0,
      manufacturer: existingDetail?.manufacturer || '',
      new_tool_record_data: existingDetail?.new_tool_record_data || null,
      replacement_type: existingDetail?.replacement_type,
      repair_parts: existingDetail?.repair_parts || [],
      brand: existingDetail?.brand || '',
      price: price,
      wear_image: existingDetail?.wear_image_url || existingDetail?.wear_image || '',
      old_tool_record_data: existingDetail?.old_tool_record_data || null,
      old_photo_links: existingDetail?.old_photo_links || [],
      remark: existingDetail?.remark || '',
    };
  }).sort((a, b) => naturalSort(a.cutter_position_no, b.cutter_position_no));
};
