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
        v-html="renderInline(block.text)"
      ></p>
      <component
        :is="block.ordered ? 'ol' : 'ul'"
        v-else-if="block.type === 'list'"
        class="markdown-list"
      >
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex" v-html="renderInline(item)"></li>
      </component>
      <div v-else-if="block.type === 'table'" class="markdown-table-wrap">
        <table class="markdown-table">
          <thead>
            <tr>
              <th v-for="(cell, cellIndex) in block.headers" :key="cellIndex" v-html="renderInline(cell)"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
              <td v-for="(cell, cellIndex) in row" :key="cellIndex" v-html="renderInline(cell)"></td>
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
        <span class="section-badge"></span>
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
}>();

type MarkdownBlock =
  | { type: 'heading'; level: number; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
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
  return line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
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

const parseMarkdown = (content: string): MarkdownBlock[] => {
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

    if (line.includes('|') && isTableSeparator(lines[index + 1] || '')) {
      const headers = parseTableRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes('|')) {
        const row = parseTableRow(lines[index]);
        rows.push(headers.map((_header, cellIndex) => row[cellIndex] || ''));
        index += 1;
      }
      blocks.push({ type: 'table', headers, rows });
      continue;
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const isOrdered = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const itemLine = lines[index].trim();
        const match = isOrdered
          ? itemLine.match(/^\d+[.)]\s+(.+)$/)
          : itemLine.match(/^[-*+]\s+(.+)$/);
        if (!match) break;
        items.push(match[1].trim());
        index += 1;
      }
      blocks.push({ type: 'list', ordered: isOrdered, items });
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

const markdownBlocks = computed(() => parseMarkdown(props.content));

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
  line-height: 1.6;
}

.markdown-answer {
  line-height: 1.65;
  color: #303133;

  .markdown-heading {
    margin: 14px 0 8px;
    color: #1f2937;
    line-height: 1.4;

    &:first-child {
      margin-top: 0;
    }

    &.level-1,
    &.level-2 {
      font-size: 16px;
      font-weight: 700;
    }

    &.level-3,
    &.level-4,
    &.level-5,
    &.level-6 {
      font-size: 14px;
      font-weight: 650;
    }
  }

  .markdown-paragraph {
    margin: 6px 0;
    white-space: pre-wrap;
  }

  .markdown-list {
    margin: 6px 0;
    padding-left: 22px;

    li + li {
      margin-top: 3px;
    }
  }

  .markdown-table-wrap {
    margin: 8px 0 12px;
    max-width: 100%;
    overflow-x: auto;
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    background: #fff;
  }

  .markdown-table {
    width: 100%;
    min-width: 480px;
    border-collapse: collapse;
    font-size: 13px;

    th,
    td {
      padding: 7px 10px;
      border-right: 1px solid #ebeef5;
      border-bottom: 1px solid #ebeef5;
      text-align: left;
      white-space: nowrap;
    }

    th {
      background: #eef2f6;
      color: #303133;
      font-weight: 600;
    }

    tr:last-child td {
      border-bottom: none;
    }

    th:last-child,
    td:last-child {
      border-right: none;
    }
  }

  .markdown-divider {
    margin: 12px 0;
    border: 0;
    border-top: 1px solid #dcdfe6;
  }

  :deep(strong) {
    font-weight: 700;
    color: #1f2937;
  }

  :deep(code) {
    padding: 1px 4px;
    border-radius: 3px;
    background: #e9eef5;
    color: #c45656;
    font-family: Consolas, monospace;
    font-size: 0.92em;
  }
}

.analysis-answer {
  display: flex;
  flex-direction: column;
  gap: 10px;

  .analysis-lead {
    font-size: 14px;
    line-height: 1.6;
    color: #2c3e50;
    margin: 0;
  }

  .analysis-section {
    padding: 10px 14px;
    border-radius: 6px;
    border-left: 3px solid #dcdfe6;
    background: #fafafa;

    .analysis-section-title {
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .section-badge {
      display: inline-block;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
    }

    .section-list {
      margin: 0;
      padding-left: 18px;
      li {
        font-size: 13px;
        line-height: 1.6;
        color: #4a5568;
      }
    }

    .section-single-p {
      margin: 0;
      font-size: 13px;
      line-height: 1.6;
      color: #4a5568;
      white-space: pre-wrap;
    }

    &.conclusion {
      background: #f0f9eb;
      border-left-color: #67c23a;
      .analysis-section-title { color: #529b2e; }
    }

    &.evidence {
      background: #ecf5ff;
      border-left-color: #409eff;
      .analysis-section-title { color: #337ecc; }
    }

    &.warning {
      background: #fdf6ec;
      border-left-color: #e6a23c;
      .analysis-section-title { color: #b88230; }
    }

    &.suggestion {
      background: #f4f4f5;
      border-left-color: #909399;
      .analysis-section-title { color: #73767a; }
    }
  }
}
</style>
