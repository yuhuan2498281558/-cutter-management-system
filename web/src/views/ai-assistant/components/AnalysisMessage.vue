<template>
  <div v-if="hasMarkdown" class="markdown-answer">
    <template v-for="(block, index) in markdownBlocks" :key="index">
      <component
        :is="`h${block.level}`"
        v-if="block.type === 'heading'"
        :class="['markdown-heading', `level-${block.level}`]"
        v-html="renderInline(block.text)"
      />
      <p
        v-else-if="block.type === 'paragraph'"
        class="markdown-paragraph"
        :class="{ 'answer-note': /^(统计口径|分析范围|开仓数量为|提示：)/.test(block.text) }"
        v-html="renderInline(block.text)"
      ></p>
      <component
        :is="block.ordered ? 'ol' : 'ul'"
        v-else-if="block.type === 'list'"
        :start="block.ordered ? block.start : undefined"
        class="markdown-list"
      >
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex" v-html="renderInline(item)"></li>
      </component>
      <div v-else-if="block.type === 'raw'" class="markdown-original">
        <p v-if="block.note" class="format-note">{{ block.note }}</p>
        <pre>{{ block.text }}</pre>
      </div>
      <div
        v-else-if="block.type === 'table'"
        class="markdown-table-wrap"
        :style="{ width: `${tableMinWidth(block.headers) + 2}px` }"
        tabindex="0"
        role="region"
        aria-label="回答数据表，可横向滚动"
      >
        <table class="markdown-table" :style="{ minWidth: `${tableMinWidth(block.headers)}px` }">
          <colgroup>
            <col v-for="(cell, cellIndex) in block.headers" :key="cellIndex" :style="tableColumnStyle(block.headers, cellIndex)" />
          </colgroup>
          <thead>
            <tr>
              <th v-for="(cell, cellIndex) in block.headers" :key="cellIndex" :class="{ numeric: isNumericColumn(cell) }" scope="col" v-html="renderInline(cell)"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
              <td v-for="(cell, cellIndex) in row" :key="cellIndex" :class="{ numeric: isNumericColumn(block.headers[cellIndex]) }" v-html="renderInline(cell)"></td>
            </tr>
          </tbody>
        </table>
      </div>
      <hr v-else-if="block.type === 'divider'" class="markdown-divider" />
    </template>
  </div>
  <div v-else-if="!parsed.sections.length" class="plain-answer">
    {{ content }}
  </div>
  <div v-else class="analysis-answer">
    <p v-if="parsed.lead" class="analysis-lead">{{ parsed.lead }}</p>
    <div
      v-for="(section, index) in parsed.sections"
      :key="index"
      :class="['analysis-section', section.kind]"
    >
      <div class="analysis-section-title">
        {{ section.title }}
      </div>
      <ul v-if="section.items.length > 1" class="section-list">
        <li v-for="(item, idx) in section.items" :key="idx">{{ item }}</li>
      </ul>
      <p v-else class="section-single-p">
        {{ splitSingleItem(section.items[0] || '') }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { AnalysisSection, ParsedAnalysisMessage } from '../types';
import { SECTION_TITLES } from '../constants';

const props = defineProps<{
  content: string;
  streaming?: boolean;
}>();

type MarkdownBlock =
  | { type: 'heading'; level: number; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[]; start?: number }
  | { type: 'raw'; text: string; note?: string }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'divider' };

const escapeHtml = (text: string) => {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
};

// 只在完整转义后的文本上开放 strong/code 两种固定标签，不接受模型输出的原始 HTML。
const renderInline = (text: string) => {
  return escapeHtml(text).replace(
    /\*\*([^*]+?)\*\*|`([^`]+?)`/g,
    (_match, strongText, codeText) => (
      strongText !== undefined
        ? `<strong>${strongText}</strong>`
        : `<code>${codeText}</code>`
    )
  );
};

const isTableSeparator = (line: string) => {
  const cells = line.trim().replace(/^\||\|$/g, '').split('|');
  return cells.length > 1 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/.test(cell));
};

const parseTableRow = (line: string) => {
  const row = line.trim().replace(/^\||\|$/g, '');
  const cells: string[] = [];
  let cell = '';
  for (let index = 0; index < row.length; index += 1) {
    if (row[index] === '\\' && /[\\|]/.test(row[index + 1] || '')) {
      cell += row[++index];
    } else if (row[index] === '|') {
      cells.push(cell.trim());
      cell = '';
    } else cell += row[index];
  }
  cells.push(cell.trim());
  return cells;
};

const isNumericColumn = (header: string) => {
  const label = header || '';
  if (/来源|名称|类型|环段|范围|各地层关联次数|最短\s*\/\s*最长/.test(label)) return false;
  return /次数|记录数|观测数|数量|安装数|服役数|在役数|服役（|检查（|更换（|更换率|异常率|间隔|时长|占比|环数|寿命|推进|距离|推力|扭矩|转速|贯入|成本|费用|价格|单价|金额|样本数|样本量|采样点数|异常数/.test(label)
    || /^(均值|平均值?|最小值?|最大值?|中位数)([（(]|$)/.test(label);
};

// 列宽只依赖表头，后续行追加长值时不会重新分配已显示列的宽度。
const tableColumnWidth = (header: string) => {
  if (/各地层关联次数/.test(header)) return 600;
  if (/主要磨损|说明|备注|依据|限制|详情|建议/.test(header)) return 400;
  if (isNumericColumn(header)) return Math.max(112, Math.min(168, header.length * 13 + 24));
  if (/^(刀位|序号|排名)$/.test(header)) return 72;
  if (/^(刀具类型|刀型|磨损状态|状态|地层类型)$/.test(header)) return 128;
  return 180;
};

const tableMinWidth = (headers: string[]) => headers.reduce((width, header) => width + tableColumnWidth(header), 0);

const tableColumnStyle = (headers: string[], index: number) => {
  return { width: `${tableColumnWidth(headers[index])}px` };
};

const startsBlock = (lines: string[], index: number) => {
  const line = lines[index]?.trim() || '';
  const next = lines[index + 1]?.trim() || '';
  return (
    !line
    || /^#{1,6}\s+/.test(line)
    || /^([-*_])\1{2,}$/.test(line)
    || /^[-*+]\s+/.test(line)
    || /^\d+[.)]\s+/.test(line)
    || (line.includes('|') && isTableSeparator(next))
  );
};

const parseMarkdown = (content: string, streaming = false): MarkdownBlock[] => {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }

    if (/^([-*_])\1{2,}$/.test(line)) {
      blocks.push({ type: 'divider' });
      index += 1;
      continue;
    }

    if (line.includes('|') && isTableSeparator(lines[index + 1] || '') && (!streaming || index + 1 < lines.length - 1)) {
      const tableStart = index;
      const headers = parseTableRow(line);
      const rows: string[][] = [];
      let malformed = parseTableRow(lines[index + 1]).length !== headers.length;
      index += 2;
      while (index < lines.length) {
        // 最后一行仍可能继续收到单元格或分隔符。等换行/结束再提交该行，
        // 避免每次追加字符都在 table/raw 之间切换并销毁整张表。
        if (streaming && index === lines.length - 1) {
          index += 1;
          break;
        }
        if (!lines[index].trim().includes('|')) break;
        const row = parseTableRow(lines[index]);
        if (row.length !== headers.length) malformed = true;
        rows.push(row);
        index += 1;
      }
      if (malformed) {
        blocks.push({
          type: 'raw',
          text: lines.slice(tableStart, index).join('\n'),
          note: streaming ? undefined : '表格列数不一致，已保留原文。',
        });
      } else blocks.push({ type: 'table', headers, rows });
      continue;
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const listStart = index;
      const isOrdered = Boolean(ordered);
      const items: string[] = [];
      const indentOf = (text: string) => (text.match(/^\s*/)?.[0] || '').replace(/\t/g, '    ').length;
      const baseIndent = indentOf(lines[index]);
      let unsupported = baseIndent > 0;
      while (index < lines.length) {
        const itemLine = lines[index].trim();
        if (!itemLine && index + 1 < lines.length && (/^\s*(?:[-*+]|\d+[.)])\s+/.test(lines[index + 1]) || indentOf(lines[index + 1]) > baseIndent)) {
          index += 1;
          continue;
        }
        const match = isOrdered
          ? itemLine.match(/^\d+[.)]\s+(.+)$/)
          : itemLine.match(/^[-*+]\s+(.+)$/);
        const anyListItem = /^(?:[-*+]|\d+[.)])\s+/.test(itemLine);
        if (!match || indentOf(lines[index]) !== baseIndent) {
          if (anyListItem || (itemLine && indentOf(lines[index]) > baseIndent)) {
            unsupported = true;
            index += 1;
            continue;
          }
          break;
        }
        items.push(match[1].trim());
        index += 1;
      }
      if (unsupported) blocks.push({ type: 'raw', text: lines.slice(listStart, index).join('\n') });
      else blocks.push({ type: 'list', ordered: isOrdered, items, ...(isOrdered ? { start: Number.parseInt(line, 10) } : {}) });
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && !startsBlock(lines, index)) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: 'paragraph', text: paragraph.join('\n') });
  }

  return blocks;
};

const markdownBlocks = computed(() => parseMarkdown(props.content, props.streaming));

const hasMarkdown = computed(() => (
  markdownBlocks.value.some((block) => block.type !== 'paragraph')
  || /\*\*[^*]+\*\*|`[^`]+`/.test(props.content)
));

const normalizeTitle = (title: string) => title.replace(/[：:]\s*$/, '').trim();

const sectionKind = (title: string): AnalysisSection['kind'] => {
  if (title.includes('结论')) return 'conclusion';
  if (title.includes('依据') || title.includes('发现')) return 'evidence';
  if (title.includes('注意')) return 'warning';
  if (title.includes('建议')) return 'suggestion';
  return 'default';
};

const splitSingleItem = (text: string) => {
  return text
    .split('\n')
    .map((line) => line.trim().replace(/^[-•]\s*/, ''))
    .filter(Boolean)
    .join('\n');
};

const parseAnalysisMessage = (content: string): ParsedAnalysisMessage => {
  const lines = content.split('\n');
  const sections: AnalysisSection[] = [];
  const lead: string[] = [];
  let current: AnalysisSection | null = null;

  const pushCurrent = () => {
    if (current && current.items.length) sections.push(current);
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;

    const inlineTitle = SECTION_TITLES.find((title) => line.startsWith(`${title}：`) || line.startsWith(`${title}:`));
    if (inlineTitle) {
      pushCurrent();
      const rest = line.slice(inlineTitle.length + 1).trim();
      current = {
        title: inlineTitle,
        kind: sectionKind(inlineTitle),
        items: rest ? [rest] : [],
      };
      continue;
    }

    const pureTitle = SECTION_TITLES.find((title) => normalizeTitle(line) === title);
    if (pureTitle) {
      pushCurrent();
      current = { title: pureTitle, kind: sectionKind(pureTitle), items: [] };
      continue;
    }

    if (current) current.items.push(line.replace(/^[-•]\s*/, ''));
    else lead.push(line);
  }

  pushCurrent();

  return {
    lead: lead.join('\n'),
    sections,
  };
};

const parsed = computed(() => parseAnalysisMessage(props.content));
</script>

<style scoped lang="scss">
.plain-answer {
  white-space: pre-wrap;
  line-height: 1.65;
}

.markdown-answer {
  line-height: 1.65;
  color: var(--el-text-color-regular);

  .markdown-original {
    margin: 8px 0;

    pre {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: inherit;
      tab-size: 4;
    }

    .format-note {
      margin: 0 0 4px;
      color: var(--el-text-color-secondary);
      font-size: 12px;
    }
  }
  font-variant-numeric: tabular-nums;

  .markdown-heading {
    margin: 20px 0 8px;
    color: var(--el-text-color-primary);
    line-height: 1.4;

    &:first-child {
      margin-top: 0;
    }

    &.level-1,
    &.level-2 {
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.2px;
    }

    &.level-3,
    &.level-4,
    &.level-5,
    &.level-6 {
      font-size: 14px;
      font-weight: 600;
    }
  }

  .markdown-paragraph {
    margin: 8px 0;
    white-space: pre-wrap;

    &.answer-note {
      color: var(--el-text-color-secondary);
      font-size: 12px;
    }
  }

  .markdown-list {
    margin: 10px 0;
    padding-left: 20px;

    li + li {
      margin-top: 5px;
    }
  }

  .markdown-table-wrap {
    margin: 10px 0 8px;
    box-sizing: border-box;
    max-width: 100%;
    overflow-x: auto;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 4px;

    &:focus-visible {
      outline: 2px solid var(--el-color-primary);
      outline-offset: 2px;
    }
  }

  .markdown-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    font-size: 13px;
    line-height: 1.55;

    th,
    td {
      padding: 7px 10px;
      border-bottom: 1px solid var(--el-border-color-lighter);
      text-align: center;
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: normal;
      vertical-align: middle;
    }

    th {
      background: var(--el-fill-color-light);
      color: var(--el-text-color-primary);
      font-weight: 600;
      vertical-align: middle;
    }

    tbody tr:nth-child(even) {
      background: var(--el-fill-color-lighter);
    }

    tr:last-child td {
      border-bottom: none;
    }

    tbody tr:hover {
      background: var(--el-fill-color-lighter);
    }
  }

  .markdown-divider {
    margin: 12px 0;
    border: 0;
    border-top: 1px solid var(--el-border-color-lighter);
  }

  :deep(strong) {
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  :deep(code) {
    padding: 1px 4px;
    border-radius: 3px;
    background: var(--el-fill-color);
    color: var(--el-text-color-primary);
    font-family: Consolas, monospace;
    font-size: 0.92em;
  }
}

.analysis-answer {
  display: flex;
  flex-direction: column;
  gap: 20px;

  .analysis-lead {
    font-size: 14px;
    line-height: 1.6;
    color: var(--el-text-color-regular);
    margin: 0;
  }

  .analysis-section {
    padding: 0;

    .analysis-section-title {
      font-size: 14px;
      color: var(--el-text-color-primary);
      font-weight: 600;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .section-list {
      margin: 0;
      padding-left: 18px;
      li {
        font-size: 13px;
        line-height: 1.6;
        color: var(--el-text-color-regular);
      }
    }

    .section-single-p {
      margin: 0;
      font-size: 13px;
      line-height: 1.6;
      color: var(--el-text-color-regular);
      white-space: pre-wrap;
    }

  }
}
</style>
