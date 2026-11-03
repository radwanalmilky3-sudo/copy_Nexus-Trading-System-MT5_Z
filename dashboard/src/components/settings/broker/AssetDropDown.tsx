import * as React from 'react';
import { ChevronDown, Search, X } from 'lucide-react';
import * as Popover from '@radix-ui/react-popover';
import type { BrokerSymbol } from './types';
import { SYMBOL_COLUMNS, filterSymbols, nextSortDir, sortSymbols, type SymbolSortKey } from './symbol-table';

export function AssetDropDown({symbols,selected,loading,onToggle,onClear}:{symbols:BrokerSymbol[];selected:string[];loading:boolean;onToggle:(name:string)=>void;onClear:()=>void}){
  const [open,setOpen]=React.useState(false);
  const [filters,setFilters]=React.useState({category:'',name:'',description:''});
  const [sort,setSort]=React.useState<{key:SymbolSortKey;dir:'asc'|'desc'}>({key:'name',dir:'asc'});
  const rows=sortSymbols(filterSymbols(symbols,filters),sort.key,sort.dir);
  return <Popover.Root open={open} onOpenChange={setOpen}>
    <div className="flex w-full items-center rounded border border-border-primary bg-bg-primary focus-within:border-neon-cyan">
      <Popover.Trigger asChild><button type="button" aria-label="اختيار الأصول من MT5" className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-sm"><span dir="ltr" className="flex-1 truncate text-right">{selected.length?selected.join(', '):loading?'جارٍ تحميل الأصول…':'اختر الأصول من MT5'}</span><ChevronDown size={16} className={open?'rotate-180':''}/></button></Popover.Trigger>
      <button type="button" aria-label="مسح الأصول المختارة" disabled={!selected.length} onClick={onClear} className="p-2 text-text-muted hover:text-text-primary disabled:opacity-30"><X size={16}/></button>
    </div>
    <Popover.Portal><Popover.Content dir="rtl" align="start" sideOffset={4} aria-label="جدول اختيار أصول MT5" className="z-50 w-[var(--radix-popover-trigger-width)] min-w-[min(680px,92vw)] max-w-[92vw] rounded-md border border-border-primary bg-bg-primary p-4 text-text-primary shadow-2xl">
      <div className="max-h-80 overflow-auto"><table className="w-full text-right text-sm [&_th]:px-3 [&_td]:px-3 [&_td]:py-2 [&_tr]:border-b [&_tr]:border-border-primary" aria-label="أصول MT5 المكتشفة">
        <thead className="sticky top-0 bg-bg-primary"><tr><th scope="col" className="w-10"><span className="sr-only">اختيار</span></th>{SYMBOL_COLUMNS.map(col=><th key={col.key} scope="col" aria-sort={sort.key===col.key?(sort.dir==='asc'?'ascending':'descending'):'none'} className="py-2 font-medium"><button type="button" className="flex items-center gap-1" onClick={()=>setSort(s=>({key:col.key,dir:nextSortDir(s,col.key)}))}>{col.label}<span aria-hidden="true" className="text-[10px] text-text-muted">{sort.key===col.key?(sort.dir==='asc'?'▲':'▼'):'↕'}</span></button></th>)}</tr>
          <tr><td/>{SYMBOL_COLUMNS.map(col=><td key={col.key}><label className="flex items-center gap-1"><Search size={14} aria-hidden="true"/><input aria-label={`بحث ${col.label}`} value={filters[col.key]} onChange={e=>setFilters({...filters,[col.key]:e.target.value})} className="w-full min-w-0 bg-transparent py-2 outline-none focus:ring-1 focus:ring-neon-cyan"/></label></td>)}</tr></thead>
        <tbody>{rows.map(row=><tr key={row.name} className={selected.includes(row.name)?'bg-neon-cyan/10':'hover:bg-bg-secondary'}><td><input type="checkbox" aria-label={`اختيار ${row.name}`} checked={selected.includes(row.name)} onChange={()=>onToggle(row.name)} className="accent-cyan-400"/></td><td>{row.category}</td><td dir="ltr">{row.name}</td><td>{row.description||'—'}</td></tr>)}</tbody>
      </table>{!rows.length&&<p role="status" className="p-4 text-center text-sm text-text-muted">{loading?'جارٍ تحميل الأصول…':'لا توجد نتائج متاحة'}</p>}</div>
      <p className="pt-2 text-xs text-text-muted">{rows.length} أصل · {selected.length} مختار</p>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}
