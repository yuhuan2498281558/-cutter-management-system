/**
 * 分页感知的序号列 formatter，供各 CRUD 模块复用
 */
export function createIndexFormatter(crudExpose: any) {
  return (context: any) => {
    const index = context.index ?? 1;
    const pagination = crudExpose!.crudBinding.value.pagination;
    return ((pagination!.currentPage ?? 1) - 1) * pagination!.pageSize + index + 1;
  };
}
