'use client';
import { Fragment, memo, useCallback, useMemo, useState } from 'react';
import { Activity, Brain, Calculator, ChevronDown, ChevronLeft, Database, Globe, Layout, Newspaper, Share2, Shield, Users, Zap, type LucideIcon } from 'lucide-react';
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import ErrorFixCell from './ErrorFixCell';
import ProgressCell from './ProgressCell';

export type ProgressItem = { id:string; name:string; description:string; parent_id:string|null; error?:string|null; fix?:string|null; notes?:string; status?:string; is_current?:boolean; start_time?:string|null; end_time?:string|null; [key:string]: string|number|boolean|null|undefined };
const cols = [['code','كود'],['database','قاعدة بيانات'],['dashboard','واجهة'],['security','أمان'],['redis','Redis Streams'],['ml','ML'],['tests','اختبارات'],['infra','بنية تحتية'],['audit','تدقيق']] as const;
const icons: Record<string, LucideIcon> = { shared: Share2, 'nexus-data': Database, 'nexus-api': Globe, 'nexus-features': Calculator, 'nexus-ml': Brain, 'nexus-agents': Users, 'nexus-news': Newspaper, 'nexus-risk': Shield, 'nexus-executor': Zap, 'nexus-monitor': Activity, frontend: Layout, infrastructure: Activity };
const legacyKeys: Record<string, string> = { dashboard: 'ui', infra: 'infrastructure' };
const readNum = (item: ProgressItem, key: string): number | null => {
  const value = item[key];
  if (typeof value === 'number') return value;
  const legacyValue = legacyKeys[key] ? item[legacyKeys[key]] : null;
  return typeof legacyValue === 'number' ? Number(legacyValue) : null;
};
const valueColor = (value: unknown) => typeof value !== 'number' ? 'text-text-muted' : value > 70 ? 'text-neon-green' : value >= 40 ? 'text-yellow-400' : 'text-neon-red';
type Rollup = { display: Record<string, number|null>; stored: Record<string, number|null>; fromChildren: Record<string, boolean>; aggregated: boolean };
type RowProps = {
  item: ProgressItem;
  level: number;
  openId: string | null;
  activeIds: Set<string>;
  childrenByParent: Record<string, ProgressItem[]>;
  rollupMap: Record<string, Rollup>;
  onToggle: (id: string) => void;
};

function ProgressRow({ item, level, openId, activeIds, childrenByParent, rollupMap, onToggle }: RowProps) {
  const children = childrenByParent[item.id] || [];
  const hasChildren = children.length > 0;
  const isExpanded = openId === item.id;
  const done = item.status === 'done';
  const active = activeIds.has(item.id);
  const rollup: Rollup | undefined = rollupMap[item.id];
  const Icon = icons[item.id] || (level === 0 ? Activity : null);
  const storedTitle = rollup ? cols.filter(([key]) => typeof rollup.stored[key] === 'number').map(([key, label]) => `${label}: ${rollup.stored[key]}%`).join('، ') : '';
  const row = <tr className={`border-b border-border-primary/50 ${done?'bg-neon-green/10':active?'bg-neon-cyan/10':'hover:bg-bg-card-hover'}`}>
    <td className={`p-2 ${level ? 'ps-7 text-text-secondary' : 'font-bold text-text-primary'}`}><button className="inline-flex items-center gap-1" onClick={() => hasChildren && onToggle(item.id)}>{hasChildren ? (isExpanded ? <ChevronDown size={13}/> : <ChevronLeft size={13}/>) : <span className="w-[13px]"/>}{Icon && <Icon size={14} className="text-neon-cyan"/>}{item.name}</button>{rollup?.aggregated && <span className="ms-1 rounded border border-neon-cyan/40 bg-neon-cyan/10 px-1 text-[9px] font-bold text-neon-cyan" title={storedTitle ? `القيم المخزنة: ${storedTitle}` : 'متوسط قيم العناصر الفرعية'}>Σ</span>}</td>
    <td className="p-2 text-text-muted">{item.description}{item.notes&&<div className="text-yellow-400">{item.notes}</div>}</td>
    <td className="p-2"><ErrorFixCell error={item.error} fix={null}/></td><td className="p-2"><ErrorFixCell error={null} fix={item.fix}/></td>
    {cols.map(([key])=>{
      const storedValue = rollup && rollup.fromChildren[key] && typeof rollup.stored[key] === 'number' ? rollup.stored[key] : null;
      return <td key={key} className="p-2 text-center" title={storedValue !== null ? `القيمة المخزنة: ${storedValue}%` : undefined}><ProgressCell value={rollup ? rollup.display[key] : readNum(item, key)} isActive={active} status={item.status} showSpinner={level === 0}/></td>;
    })}
  </tr>;
  return <Fragment key={item.id}>{row}{isExpanded && hasChildren && <tr><td colSpan={13} className="p-0 bg-[#0f172a]"><table className="w-full"><tbody>{children.map(child => <ProgressRow key={child.id} item={child} level={level + 1} openId={openId} activeIds={activeIds} childrenByParent={childrenByParent} rollupMap={rollupMap} onToggle={onToggle}/>)}</tbody></table></td></tr>}</Fragment>;
}

const MemoProgressRow = memo(ProgressRow);

function HierarchicalTable({ items, currentTaskId }: { items: ProgressItem[]; currentTaskId?: string }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const childrenByParent = useMemo(() => items.reduce<Record<string, ProgressItem[]>>((groups, item) => {
    if (item.parent_id) (groups[item.parent_id] ||= []).push(item);
    return groups;
  }, {}), [items]);
  const roots = useMemo(() => {
    const ids = new Set(items.map(x => x.id));
    return items.filter(x => !x.parent_id || !ids.has(x.parent_id));
  }, [items]);
  const activeIds = useMemo(() => {
    const byId = new Map(items.map(x => [x.id, x]));
    const active = new Set<string>();
    for (const seed of items.filter(x => x.id === currentTaskId || x.is_current === true)) {
      let cursor: ProgressItem | undefined = seed;
      while (cursor) {
        active.add(cursor.id);
        cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
      }
    }
    return active;
  }, [items, currentTaskId]);
  const rollupMap = useMemo(() => {
    const map: Record<string, Rollup> = {};
    for (const item of items) {
      const children = childrenByParent[item.id];
      if (!children?.length) continue;
      const stored: Record<string, number|null> = {};
      const display: Record<string, number|null> = {};
      const fromChildren: Record<string, boolean> = {};
      let aggregated = false;
      for (const [key] of cols) {
        stored[key] = readNum(item, key);
        const values = children.map(child => readNum(child, key)).filter((v): v is number => v !== null);
        if (values.length) {
          display[key] = Math.round(values.reduce((sum, v) => sum + v, 0) / values.length);
          fromChildren[key] = true;
          aggregated = true;
        } else {
          display[key] = stored[key];
          fromChildren[key] = false;
        }
      }
      map[item.id] = { display, stored, fromChildren, aggregated };
    }
    return map;
  }, [items, childrenByParent]);
  const categoryData = useMemo(() => cols.map(([key, name]) => ({ name, value: items.reduce((sum, x) => sum + (readNum(x, key) ?? 0), 0) / Math.max(items.filter(x => readNum(x, key) !== null).length, 1) })), [items]);
  const serviceData = useMemo(() => roots.map(x => ({ name: x.name, value: readNum(x, 'code') ?? 0 })), [roots]);
  const onToggle = useCallback((id: string) => setOpen(v => v[id] ? {} : {[id]: true}), []);
  if (!items.length) return <div className="rounded border border-border-primary bg-bg-secondary p-8 text-center text-sm text-text-muted">لا توجد بيانات تقدم لعرضها</div>;
  const openEntry = Object.entries(open).find(([, expanded]) => expanded);
  const openId = openEntry ? openEntry[0] : null;
  const pieColors = ['#22c55e','#06b6d4','#a855f7','#facc15','#f97316','#ef4444','#14b8a6','#e879f9','#84cc16'];
  return <div className="space-y-4"><div className="grid gap-3 xl:grid-cols-2"><div className="rounded border border-border-primary bg-bg-secondary p-3"><div className="mb-2 text-[11px] font-bold text-text-secondary">توزيع الفئات</div><div className="h-56"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={categoryData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={75} label={({name})=>name}>{categoryData.map((_,i)=><Cell key={i} fill={pieColors[i%pieColors.length]}/>)}</Pie><Tooltip formatter={(v:number)=>`${v.toFixed(1)}%`} /></PieChart></ResponsiveContainer></div></div><div className="rounded border border-border-primary bg-bg-secondary p-3"><div className="mb-2 text-[11px] font-bold text-text-secondary">تقدم الخدمات</div><div className="h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={serviceData} layout="vertical" margin={{left:30,right:15}}><XAxis type="number" domain={[0,100]} hide/><YAxis type="category" dataKey="name" width={100} tick={{fontSize:9,fill:'#a1a1aa'}}/><Tooltip formatter={(v:number)=>`${v}%`}/><Bar dataKey="value" fill="#06b6d4" radius={[0,4,4,0]}/></BarChart></ResponsiveContainer></div></div></div><div className="overflow-x-auto rounded border border-border-primary"><table className="min-w-[1800px] w-full text-start text-[11px]"><thead><tr className="border-b border-border-primary bg-bg-tertiary text-text-muted"><th className="p-2">البند</th><th className="p-2">شرح مختصر</th><th className="p-2">الخطأ</th><th className="p-2">الإصلاح</th>{cols.map(([,label])=><th key={label} className="p-2 text-center">{label}</th>)}</tr></thead><tbody>{roots.map(item => <MemoProgressRow key={item.id} item={item} level={0} openId={openId} activeIds={activeIds} childrenByParent={childrenByParent} rollupMap={rollupMap} onToggle={onToggle}/>)}</tbody></table></div></div>;
}

export default memo(HierarchicalTable);
