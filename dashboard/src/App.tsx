import { useState, useEffect, useRef, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Toaster, toast } from 'sonner';
import { Activity, TrendingUp, TrendingDown, Pause, Play, AlertTriangle, DollarSign, BarChart3, Clock, Zap, Target, Percent, Wallet, Wifi, WifiOff, Settings, Hand, CircleDot, RefreshCw, FlaskConical, Calculator, ClipboardList, Cog, Power, Loader2, Radio, History, Gauge, ShieldCheck, Eye } from 'lucide-react';
import CredentialManager from './components/CredentialManager';
import StrategyControl from './components/StrategyControl';
import './App.css';

// ─── TYPES ─────────────────────────────────────────────────
interface Position { ticket: number; symbol: string; direction: string; volume: number; openPrice: number; currentPrice: number; sl: number; tp: number; profit: number; openTime: string; }
interface Trade { ticket: number; symbol: string; direction: string; volume: number; entryPrice: number; exitPrice: number; profit: number; commission: number; openTime: string; closeTime: string; }
interface BacktestResult { name: string; trades: number; win_rate: number; pnl: number; return_pct: number; max_dd: number; profit_factor: number; sharpe: number; status: string; }
export type { BacktestResult };
interface Strategy { id: string; name: string; symbol: string; type: string; instrument_category: string; }
interface StrategyCfg { enabled: boolean; risk_pct: number; }
interface Job { id: string; type: string; status: string; progress: number; created_at: string; completed_at?: string; error?: string; }
interface AccountData { balance: number; equity: number; profit: number; margin: number; name?: string; broker?: string; }
interface PerformanceData { xau_asian?: Record<string, unknown>; xau_ny?: Record<string, unknown>; monte_carlo?: Record<string, unknown>; }
interface BotStatus { phase: string; zone: string; is_trading: boolean; is_paper: boolean; provider: string; connection: string; active_strategies: number; }
interface CredStatus { configured: boolean; account_id?: string; prop_firm?: string; phase?: string; account_size?: number; region?: string; }
interface PropFirm { id: string; name: string; phases: string[]; }

// ─── CONSTANTS ─────────────────────────────────────────────
const API_BASE = '';
const POLL_INTERVAL = 5000;
const ZS: Record<string, { bg: string; border: string; text: string; dot: string; label: string }> = {
  safe: { bg: 'bg-emerald-500/15', border: 'border-emerald-400/30', text: 'text-emerald-300', dot: 'bg-emerald-400', label: 'SAFE' },
  caution: { bg: 'bg-yellow-500/15', border: 'border-yellow-400/30', text: 'text-yellow-300', dot: 'bg-yellow-400', label: 'CAUTION' },
  danger: { bg: 'bg-red-500/15', border: 'border-red-400/30', text: 'text-red-300', dot: 'bg-red-400', label: 'DANGER' },
  blocked: { bg: 'bg-red-600/20', border: 'border-red-500/40', text: 'text-red-200', dot: 'bg-red-500', label: 'BLOCKED' },
};

// ─── HELPERS ───────────────────────────────────────────────
function ZoneIndicator({ zone }: { zone: string }) {
  const z = ZS[zone] || ZS.safe;
  return <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border ${z.bg} ${z.border}`}><div className={`w-2.5 h-2.5 rounded-full ${z.dot}`} /><span className={`text-xs font-bold uppercase tracking-wider ${z.text}`}>{z.label}</span></div>;
}

function StatCard({ title, value, subtitle, icon: Icon, trend }: { title: string; value: string; subtitle?: string; icon: React.ElementType; trend?: 'up' | 'down' }) {
  const bg = trend === 'up' ? 'bg-emerald-400/10' : trend === 'down' ? 'bg-red-400/10' : 'bg-slate-700/40';
  const ic = trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-red-400' : 'text-slate-300';
  return <Card className="bg-slate-900 border-slate-700"><CardContent className="p-4"><div className="flex items-start justify-between"><div className="space-y-1"><p className="text-[11px] font-semibold text-slate-300 uppercase tracking-widest">{title}</p><p className="text-xl font-bold text-white">{value}</p>{subtitle && <p className="text-[11px] text-slate-400">{subtitle}</p>}</div><div className={`p-2 rounded-lg ${bg}`}><Icon className={`h-4 w-4 ${ic}`} /></div></div></CardContent></Card>;
}

function ToggleSwitch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return <div className="flex items-center justify-between py-1.5"><span className="text-sm text-slate-200 font-medium">{label}</span><button onClick={() => onChange(!checked)} className={`relative w-10 h-5 rounded-full transition-colors ${checked ? 'bg-emerald-500' : 'bg-slate-600'}`}><div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : ''}`} /></button></div>;
}

function ActionButton({ icon: Icon, label, description, onClick, loading = false, variant = 'primary' }: { icon: React.ElementType; label: string; description: string; onClick: () => void; loading?: boolean; variant?: 'primary' | 'danger' | 'warning' }) {
  const vs = { primary: 'bg-blue-600 hover:bg-blue-700 border-blue-500', warning: 'bg-amber-600 hover:bg-amber-700 border-amber-500', danger: 'bg-red-600 hover:bg-red-700 border-red-500' };
  return <button onClick={onClick} disabled={loading} className={`w-full p-3 rounded-lg border ${vs[variant]} text-white text-left transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed`}><div className="flex items-center gap-3"><div className="p-2 rounded-md bg-white/10">{loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Icon className="h-5 w-5" />}</div><div><p className="text-sm font-semibold">{label}</p><p className="text-[11px] text-white/60">{description}</p></div></div></button>;
}

function JobRow({ job }: { job: Job }) {
  return <div className="flex items-center gap-3 p-2 rounded-md bg-slate-800/50 border border-slate-700"><div className={`w-2 h-2 rounded-full ${job.status === 'running' ? 'bg-amber-400 animate-pulse' : job.status === 'completed' ? 'bg-emerald-400' : job.status === 'failed' ? 'bg-red-400' : 'bg-slate-500'}`} /><div className="flex-1 min-w-0"><div className="flex items-center justify-between"><span className="text-xs font-medium text-slate-200 truncate">{job.type} <span className="text-slate-500">#{job.id}</span></span><span className={`text-[10px] font-bold uppercase ${job.status === 'running' ? 'text-amber-400' : job.status === 'completed' ? 'text-emerald-400' : job.status === 'failed' ? 'text-red-400' : 'text-slate-400'}`}>{job.status}</span></div>{job.status === 'running' && <div className="mt-1 w-full h-1.5 rounded-full bg-slate-700 overflow-hidden"><div className="h-full bg-amber-400 rounded-full transition-all" style={{ width: `${job.progress || 0}%` }} /></div>}</div></div>;
}

async function apiFetch(path: string, opts?: RequestInit) {
  const r = await fetch(`${API_BASE}${path}`, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

const fmtTime = (d: string) => new Date(d).toLocaleTimeString();
const fmtDate = (d: string) => new Date(d).toLocaleDateString();

// ─── MAIN APP ──────────────────────────────────────────────
export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [lastUpdated, setLastUpdated] = useState(new Date());

  // Data states
  const [credStatus, setCredStatus] = useState<CredStatus | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [account, setAccount] = useState<AccountData>({ balance: 0, equity: 0, profit: 0, margin: 0 });
  const [performance, setPerformance] = useState<PerformanceData | null>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyConfig, setStrategyConfig] = useState<Record<string, StrategyCfg>>({});
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [propFirms, setPropFirms] = useState<PropFirm[]>([]);

  // UI states
  const [showEmergency, setShowEmergency] = useState(false);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [isTrading, setIsTrading] = useState(false);
  const [isPaper, setIsPaper] = useState(true);
  const [riskPct, setRiskPct] = useState(0.5);
  const [tradingMode, setTradingMode] = useState<'auto' | 'manual'>('auto');
  const [connectionType, setConnectionType] = useState<'metaapi' | 'mt5'>('metaapi');
  const [btStrategy, setBtStrategy] = useState<string>('');
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doToast = useCallback((msg: string) => { if (toastTimer.current) clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => toast.success(msg), 100); }, []);
  const doError = useCallback((msg: string) => toast.error(msg), []);

  // Fetch functions
  const fetchCredentials = useCallback(async () => { try { setCredStatus(await apiFetch('/api/credentials/status')); } catch { /* silent */ } }, []);
  const fetchStatus = useCallback(async () => { try { const d = await apiFetch('/api/status'); setBotStatus(d); setIsTrading(d.is_trading); setIsPaper(d.is_paper); } catch { /* silent */ } }, []);
  const fetchAccount = useCallback(async () => { try { setAccount(await apiFetch('/api/account')); } catch { /* silent */ } }, []);
  const fetchPerformance = useCallback(async () => { try { setPerformance(await apiFetch('/api/performance')); } catch { /* silent */ } }, []);
  const fetchStrategies = useCallback(async () => { try { const d = await apiFetch('/api/strategies'); if (d.strategies) setStrategies(d.strategies); } catch { /* silent */ } }, []);
  const fetchStrategyConfig = useCallback(async () => { try { setStrategyConfig(await apiFetch('/api/strategies/config')); } catch { /* silent */ } }, []);
  const fetchPositions = useCallback(async () => { try { const d = await apiFetch('/api/positions'); if (Array.isArray(d)) setPositions(d); } catch { /* silent */ } }, []);
  const fetchTrades = useCallback(async () => { try { const d = await apiFetch('/api/trades'); if (Array.isArray(d)) setTrades(d); } catch { /* silent */ } }, []);
  const fetchJobs = useCallback(async () => { try { const d = await apiFetch('/api/jobs'); if (Array.isArray(d)) { setJobs(d); if (!d.find((j: Job) => j.status === 'running')) setRunningAction(null); } } catch { /* silent */ } }, []);
  const fetchPropFirms = useCallback(async () => { try { const d = await apiFetch('/api/prop-firms'); if (d.firms) setPropFirms(d.firms); } catch { /* silent */ } }, []);

  // Polling
  useEffect(() => {
    [fetchCredentials, fetchStatus, fetchAccount, fetchPerformance, fetchStrategies, fetchStrategyConfig, fetchPositions, fetchTrades, fetchJobs, fetchPropFirms].forEach(f => f());
    const iv = setInterval(() => { fetchStatus(); fetchAccount(); fetchPerformance(); fetchPositions(); fetchTrades(); fetchJobs(); setLastUpdated(new Date()); }, POLL_INTERVAL);
    return () => clearInterval(iv);
  }, [fetchCredentials, fetchStatus, fetchAccount, fetchPerformance, fetchStrategies, fetchStrategyConfig, fetchPositions, fetchTrades, fetchJobs, fetchPropFirms]);

  // Action handlers
  const handleToggleTrading = useCallback(async () => {
    try { const d = isTrading ? await apiFetch('/api/pause', { method: 'POST' }) : await apiFetch('/api/resume', { method: 'POST' }); setIsTrading(!isTrading); doToast(d.status || (isTrading ? 'Paused' : 'Started')); fetchStatus(); }
    catch (e: unknown) { doError(e instanceof Error ? e.message : 'Failed'); }
  }, [isTrading, doToast, doError, fetchStatus]);

  const handleEmergency = useCallback(async () => {
    setShowEmergency(false);
    try { const d = await apiFetch('/api/emergency-close', { method: 'POST' }); toast.success('Emergency close executed'); setIsTrading(false); doToast(d.status || 'Halted'); fetchPositions(); }
    catch (e: unknown) { doError(e instanceof Error ? e.message : 'Failed'); }
  }, [doToast, doError, fetchPositions]);

  const handleToggleStrategy = useCallback(async (id: string) => {
    const cur = strategyConfig[id] || { enabled: false, risk_pct: 1.0 };
    const upd = { ...cur, enabled: !cur.enabled };
    try { await apiFetch('/api/strategies/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [id]: upd }) }); setStrategyConfig(p => ({ ...p, [id]: upd })); doToast(`${id}: ${upd.enabled ? 'enabled' : 'disabled'}`); }
    catch (e: unknown) { doError(e instanceof Error ? e.message : 'Failed'); }
  }, [strategyConfig, doToast, doError]);

  const handleTogglePaper = useCallback((val: boolean) => { setIsPaper(val); doToast(val ? 'PAPER' : 'LIVE'); }, [doToast]);

  const runAction = useCallback(async (name: string, apiPath?: string, method = 'POST', body?: unknown) => {
    setRunningAction(name); toast.loading(`${name}...`);
    try { const opts: RequestInit = { method }; if (body) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(body); } if (apiPath) await apiFetch(apiPath, opts); else await new Promise(r => setTimeout(r, 1500)); toast.dismiss(); doToast(`${name} done`); fetchJobs(); }
    catch (e: unknown) { toast.dismiss(); doError(e instanceof Error ? e.message : `${name} failed`); }
    finally { setRunningAction(null); }
  }, [doToast, doError, fetchJobs]);

  // Derived data
  const limits = { dailyDDPct: 0.05, maxDDPct: 0.10, profitTarget: 0.10 };
  const accountSize = credStatus?.account_size || 10000;
  const dailyLossLimit = accountSize * limits.dailyDDPct;
  const maxDDLimit = accountSize * limits.maxDDPct;
  const profitTarget = accountSize * limits.profitTarget;
  const totalTrades = trades.length;
  const winCount = trades.filter(t => t.profit > 0).length;
  const winRate = totalTrades > 0 ? Math.round((winCount / totalTrades) * 100) : 0;
  const totalPnL = trades.reduce((s, t) => s + t.profit, 0);
  const catCount = strategies.reduce<Record<string, number>>((acc, s) => { const cfg = strategyConfig[s.id]; if (cfg?.enabled) acc[s.instrument_category || 'other'] = (acc[s.instrument_category || 'other'] || 0) + 1; return acc; }, {});
  const categories = Object.keys(catCount);
  const activeStratCount = Object.values(strategyConfig).filter(c => c?.enabled).length;
  const propFirmName = credStatus?.prop_firm || 'No Firm';
  const currentPhase = credStatus?.phase || 'phase1';
  const currentFirm = propFirms.find(f => f.id === propFirmName);
  const currentZone = botStatus?.zone || 'safe';

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100">
      <Toaster position="top-right" toastOptions={{ style: { background: '#0f172a', border: '1px solid #475569', color: '#e2e8f0' } }} />

      {/* HEADER */}
      <header className="border-b border-slate-700/50 bg-[#070b14]/95 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-400/30 flex items-center justify-center"><Activity className="h-4 w-4 text-emerald-400" /></div>
            <div><h1 className="text-sm font-bold text-white leading-tight">PropFirm Bot</h1><p className="text-[10px] text-slate-400">{propFirmName} &middot; ${accountSize.toLocaleString()} {currentPhase}</p></div>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <button onClick={() => handleTogglePaper(!isPaper)} className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border ${isPaper ? 'bg-yellow-500/10 border-yellow-400/30' : 'bg-red-500/10 border-red-400/30'}`}><div className={`w-2 h-2 rounded-full ${isPaper ? 'bg-yellow-400' : 'bg-red-400'}`} /><span className={`text-xs font-bold uppercase tracking-wider ${isPaper ? 'text-yellow-300' : 'text-red-300'}`}>{isPaper ? 'PAPER' : 'LIVE'}</span></button>
            <Badge variant="outline" className="bg-slate-800 text-slate-300 border-slate-600 text-xs"><Target className="h-3 w-3 mr-1" />{currentPhase}</Badge>
            <ZoneIndicator zone={currentZone} />
            <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/50 border border-slate-700">{botStatus?.connection === 'connected' ? <Wifi className="h-3 w-3 text-emerald-400" /> : <WifiOff className="h-3 w-3 text-red-400" />}<span className="text-[10px] text-slate-300">{connectionType === 'metaapi' ? 'MetaAPI' : 'MT5'}</span></div>
            <div className={`w-2 h-2 rounded-full ${isTrading ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : 'bg-slate-500'}`} />
            <span className="text-[10px] text-slate-300">{isTrading ? 'ACTIVE' : 'IDLE'}</span>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* STATS ROW */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard title="Balance" value={`$${(account.balance || 0).toLocaleString()}`} subtitle={`${(account.profit || 0) >= 0 ? '+' : ''}$${(account.profit || 0).toLocaleString()}`} icon={Wallet} />
          <StatCard title="Equity" value={`$${(account.equity || 0).toLocaleString()}`} subtitle="unrealized" icon={DollarSign} trend={(account.profit || 0) >= 0 ? 'up' : 'down'} />
          <StatCard title="Daily P&L" value={`${totalPnL >= 0 ? '+' : ''}$${totalPnL.toLocaleString()}`} subtitle="Today" icon={TrendingUp} trend={totalPnL >= 0 ? 'up' : 'down'} />
          <StatCard title="Win Rate" value={`${winRate}%`} subtitle={`${winCount}/${totalTrades}`} icon={Percent} trend={winRate >= 50 ? 'up' : 'down'} />
          <StatCard title="Max DD" value={`$${maxDDLimit.toLocaleString()}`} subtitle={`Limit: ${(limits.maxDDPct * 100).toFixed(0)}%`} icon={TrendingDown} />
          <StatCard title="Open Pos" value={`${positions.length}`} subtitle={`Floating: $${positions.reduce((s, p) => s + p.profit, 0)}`} icon={Radio} />
        </div>

        {/* CONTROLS */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={handleToggleTrading} className={isTrading ? 'border border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20' : 'bg-emerald-600 hover:bg-emerald-700 text-white'}>{isTrading ? <><Power className="h-4 w-4 mr-2" /> Stop Bot</> : <><Play className="h-4 w-4 mr-2" /> Start Bot</>}</Button>
          <Button size="sm" variant="outline" onClick={() => setShowEmergency(true)} className="border-red-500/40 text-red-300 hover:bg-red-500/15 bg-red-500/5"><AlertTriangle className="h-4 w-4 mr-2" /> Emergency Close</Button>
          <div className="ml-auto flex items-center gap-3 text-[11px] text-slate-400"><Clock className="h-3.5 w-3.5 text-slate-500" /><span>Updated: {lastUpdated.toLocaleTimeString()}</span></div>
        </div>

        {/* TABS */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-slate-800/80 border border-slate-700 flex-wrap h-auto">
            <TabsTrigger value="overview" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Gauge className="h-3 w-3 mr-1" />Overview</TabsTrigger>
            <TabsTrigger value="positions" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Radio className="h-3 w-3 mr-1" />Positions ({positions.length})</TabsTrigger>
            <TabsTrigger value="history" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><History className="h-3 w-3 mr-1" />History ({trades.length})</TabsTrigger>
            <TabsTrigger value="strategies" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Zap className="h-3 w-3 mr-1" />Strategies</TabsTrigger>
            <TabsTrigger value="strategy-control" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Target className="h-3 w-3 mr-1" />Strategy Control</TabsTrigger>
            <TabsTrigger value="backtest" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><FlaskConical className="h-3 w-3 mr-1" />Backtest</TabsTrigger>
            <TabsTrigger value="control" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Cog className="h-3 w-3 mr-1" />Control</TabsTrigger>
            <TabsTrigger value="settings" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><ShieldCheck className="h-3 w-3 mr-1" />Settings</TabsTrigger>
          </TabsList>

          {/* OVERVIEW */}
          <TabsContent value="overview" className="space-y-4 mt-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Wallet className="h-4 w-4 text-emerald-400" />Account</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-slate-400">Balance</span><span className="text-white font-mono">${(account.balance || 0).toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Equity</span><span className="text-white font-mono">${(account.equity || 0).toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Margin</span><span className="text-white font-mono">${(account.margin || 0).toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">P&L</span><span className={`font-mono ${(account.profit || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${(account.profit || 0).toLocaleString()}</span></div>
                {account.name && <div className="flex justify-between"><span className="text-slate-400">Name</span><span className="text-white">{account.name}</span></div>}
                {account.broker && <div className="flex justify-between"><span className="text-slate-400">Broker</span><span className="text-white">{account.broker}</span></div>}
              </CardContent></Card>

              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Zap className="h-4 w-4 text-amber-400" />Strategies</CardTitle></CardHeader><CardContent className="space-y-2">
                <div className="text-2xl font-bold text-white">{activeStratCount}<span className="text-sm text-slate-400"> / {strategies.length}</span></div>
                {categories.length > 0 ? categories.map(cat => <div key={cat} className="flex justify-between text-sm"><span className="text-slate-400 capitalize">{cat}</span><span className="text-emerald-400 font-semibold">{catCount[cat]} enabled</span></div>) : <p className="text-xs text-slate-500">No strategies enabled</p>}
              </CardContent></Card>

              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><ShieldCheck className="h-4 w-4 text-blue-400" />Limits</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-slate-400">Daily DD</span><span className="text-red-400 font-mono">${dailyLossLimit.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Max DD</span><span className="text-red-400 font-mono">${maxDDLimit.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Profit Target</span><span className="text-emerald-400 font-mono">${profitTarget.toLocaleString()}</span></div>
                <div className="flex justify-between"><span className="text-slate-400">Risk/Trade</span><span className="text-yellow-400 font-mono">{riskPct}%</span></div>
              </CardContent></Card>

              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><AlertTriangle className="h-4 w-4 text-red-400" />Risk Zone</CardTitle></CardHeader><CardContent><ZoneIndicator zone={currentZone} /><p className="text-xs text-slate-400 mt-2">Active strategies: {botStatus?.active_strategies || 0}</p><p className="text-xs text-slate-400">Phase: {botStatus?.phase || currentPhase}</p></CardContent></Card>

              <Card className="bg-slate-900 border-slate-700 md:col-span-2"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><ClipboardList className="h-4 w-4 text-purple-400" />Recent Jobs</CardTitle></CardHeader><CardContent>
                {jobs.length === 0 ? <p className="text-xs text-slate-500">No jobs</p> : <div className="space-y-2">{jobs.slice(0, 3).map(j => <JobRow key={j.id} job={j} />)}{jobs.length > 3 && <button onClick={() => setActiveTab('backtest')} className="text-xs text-blue-400 hover:underline mt-1">View all {jobs.length} jobs</button>}</div>}
              </CardContent></Card>
            </div>
          </TabsContent>

          {/* POSITIONS */}
          <TabsContent value="positions" className="mt-4">
            <Card className="bg-slate-900 border-slate-700"><CardContent className="p-0">
              {positions.length === 0 ? <p className="p-6 text-center text-sm text-slate-500">No open positions</p> : <Table>
                <TableHeader><TableRow className="border-slate-700 hover:bg-transparent"><TableHead className="text-slate-300 text-xs">Ticket</TableHead><TableHead className="text-slate-300 text-xs">Symbol</TableHead><TableHead className="text-slate-300 text-xs">Dir</TableHead><TableHead className="text-slate-300 text-xs">Vol</TableHead><TableHead className="text-slate-300 text-xs">Open</TableHead><TableHead className="text-slate-300 text-xs">Current</TableHead><TableHead className="text-slate-300 text-xs">SL / TP</TableHead><TableHead className="text-slate-300 text-xs text-right">P&L</TableHead></TableRow></TableHeader>
                <TableBody>{positions.map(p => <TableRow key={p.ticket} className="border-slate-700"><TableCell className="text-slate-400 text-xs">{p.ticket}</TableCell><TableCell className="font-medium text-white text-sm">{p.symbol}</TableCell><TableCell><Badge variant="outline" className={p.direction === 'buy' ? 'border-emerald-400/40 text-emerald-300 text-xs' : 'border-red-400/40 text-red-300 text-xs'}>{p.direction.toUpperCase()}</Badge></TableCell><TableCell className="text-slate-200 text-sm">{p.volume}</TableCell><TableCell className="text-slate-200 text-sm">{p.openPrice.toFixed(p.symbol.includes('XAU') ? 2 : 4)}</TableCell><TableCell className="text-slate-200 text-sm">{p.currentPrice.toFixed(p.symbol.includes('XAU') ? 2 : 4)}</TableCell><TableCell className="text-xs text-slate-300">{p.sl} / {p.tp}</TableCell><TableCell className={`text-right font-bold text-sm ${p.profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{p.profit >= 0 ? '+' : ''}${p.profit.toLocaleString()}</TableCell></TableRow>)}</TableBody>
              </Table>}
            </CardContent></Card>
          </TabsContent>

          {/* HISTORY */}
          <TabsContent value="history" className="mt-4">
            <Card className="bg-slate-900 border-slate-700"><CardContent className="p-0">
              {trades.length === 0 ? <p className="p-6 text-center text-sm text-slate-500">No trade history</p> : <Table>
                <TableHeader><TableRow className="border-slate-700 hover:bg-transparent"><TableHead className="text-slate-300 text-xs">Ticket</TableHead><TableHead className="text-slate-300 text-xs">Symbol</TableHead><TableHead className="text-slate-300 text-xs">Dir</TableHead><TableHead className="text-slate-300 text-xs">Vol</TableHead><TableHead className="text-slate-300 text-xs">Entry</TableHead><TableHead className="text-slate-300 text-xs">Exit</TableHead><TableHead className="text-slate-300 text-xs">Open</TableHead><TableHead className="text-slate-300 text-xs">Close</TableHead><TableHead className="text-slate-300 text-xs text-right">P&L</TableHead></TableRow></TableHeader>
                <TableBody>{trades.map(t => <TableRow key={t.ticket} className="border-slate-700"><TableCell className="text-slate-400 text-xs">{t.ticket}</TableCell><TableCell className="font-medium text-white text-sm">{t.symbol}</TableCell><TableCell><Badge variant="outline" className={t.direction === 'buy' ? 'border-emerald-400/40 text-emerald-300 text-xs' : 'border-red-400/40 text-red-300 text-xs'}>{t.direction.toUpperCase()}</Badge></TableCell><TableCell className="text-slate-200 text-sm">{t.volume}</TableCell><TableCell className="text-slate-200 text-sm">{t.entryPrice.toFixed(2)}</TableCell><TableCell className="text-slate-200 text-sm">{t.exitPrice.toFixed(2)}</TableCell><TableCell className="text-xs text-slate-400">{fmtDate(t.openTime)} {fmtTime(t.openTime)}</TableCell><TableCell className="text-xs text-slate-400">{fmtDate(t.closeTime)} {fmtTime(t.closeTime)}</TableCell><TableCell className={`text-right font-bold text-sm ${t.profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{t.profit >= 0 ? '+' : ''}${t.profit.toLocaleString()}</TableCell></TableRow>)}</TableBody>
              </Table>}
            </CardContent></Card>
          </TabsContent>

          {/* STRATEGIES */}
          <TabsContent value="strategies" className="space-y-4 mt-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {strategies.map(s => {
                const cfg = strategyConfig[s.id] || { enabled: false, risk_pct: 1.0 };
                return <Card key={s.id} className={`bg-slate-900 border-slate-700 ${cfg.enabled ? 'border-l-4 border-l-emerald-500' : 'border-l-4 border-l-slate-600 opacity-70'}`}><CardHeader className="pb-2"><div className="flex items-center justify-between"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Zap className="h-4 w-4 text-amber-400" />{s.name}</CardTitle><ToggleSwitch checked={cfg.enabled} onChange={() => handleToggleStrategy(s.id)} label="" /></div><CardDescription className="text-xs text-slate-400">{s.symbol} &bull; {s.type} &bull; {s.instrument_category}</CardDescription></CardHeader><CardContent className="space-y-2 text-xs"><div className="flex items-center gap-2"><Badge variant="outline" className={cfg.enabled ? 'border-emerald-500/40 text-emerald-300 text-[10px]' : 'border-slate-600 text-slate-500 text-[10px]'}>{cfg.enabled ? 'Enabled' : 'Disabled'}</Badge><span className="text-slate-400">Risk: {cfg.risk_pct}%</span></div></CardContent></Card>;
              })}
              {strategies.length === 0 && <p className="text-center text-slate-500 text-sm col-span-2">No strategies found</p>}
            </div>
          </TabsContent>

          {/* STRATEGY CONTROL */}
          <TabsContent value="strategy-control" className="mt-4"><StrategyControl /></TabsContent>

          {/* BACKTEST */}
          <TabsContent value="backtest" className="space-y-4 mt-4">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex-1 min-w-[200px]"><Select value={btStrategy} onValueChange={setBtStrategy}><SelectTrigger className="bg-slate-800 border-slate-700 text-slate-200 text-xs"><SelectValue placeholder="Select strategy..." /></SelectTrigger><SelectContent className="bg-slate-900 border-slate-700">{strategies.map(s => <SelectItem key={s.id} value={s.id} className="text-slate-200 text-xs">{s.name}</SelectItem>)}</SelectContent></Select></div>
              {btStrategy && <span className="text-xs text-slate-400">{strategies.find(s => s.id === btStrategy)?.symbol}</span>}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <ActionButton icon={RefreshCw} label="Fetch Data" description="Download OHLCV" onClick={() => runAction('Fetch Data', '/api/data/fetch')} loading={runningAction === 'Fetch Data'} variant="primary" />
              <ActionButton icon={FlaskConical} label="Run Backtest" description="Backtest strategies" onClick={() => btStrategy ? runAction(`Backtest ${btStrategy}`, `/api/strategies/${btStrategy}/backtest`) : runAction('Backtest', '/api/backtest/run')} loading={runningAction?.startsWith('Backtest') ?? false} variant="primary" />
              <ActionButton icon={Cog} label="Optimize" description="Walk-forward tuning" onClick={() => btStrategy ? runAction(`Optimize ${btStrategy}`, `/api/strategies/${btStrategy}/optimize`) : runAction('Optimize', '/api/backtest/optimize')} loading={runningAction?.startsWith('Optimize') ?? false} variant="warning" />
              <ActionButton icon={Calculator} label="Monte Carlo" description="Simulation test" onClick={() => btStrategy ? runAction(`MC ${btStrategy}`, `/api/strategies/${btStrategy}/mc`) : runAction('Monte Carlo', '/api/backtest/mc')} loading={runningAction?.startsWith('MC') || runningAction === 'Monte Carlo' || false} variant="warning" />
              <ActionButton icon={BarChart3} label="Stress Test" description="Extreme scenarios" onClick={() => runAction('Stress Test')} loading={runningAction === 'Stress Test'} variant="warning" />
              <ActionButton icon={ClipboardList} label="Report" description="HTML + JSON report" onClick={() => runAction('Generate Report')} loading={runningAction === 'Generate Report'} variant="primary" />
            </div>
            {jobs.length > 0 && <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm text-slate-200">Job Queue</CardTitle></CardHeader><CardContent><div className="space-y-2">{jobs.map(j => <JobRow key={j.id} job={j} />)}</div></CardContent></Card>}
            {performance && <div className="space-y-4">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {Object.entries(performance).filter(([k]) => k !== 'monte_carlo').map(([key, val]: [string, unknown]) => {
                  const r = val as BacktestResult;
                  return <Card key={key} className={`bg-slate-900 border-slate-700 ${r.status === 'pass' ? 'border-l-4 border-l-emerald-500' : r.status === 'close' ? 'border-l-4 border-l-yellow-500' : 'border-l-4 border-l-red-500'}`}><CardHeader className="pb-2"><div className="flex items-center justify-between"><CardTitle className="text-sm text-slate-200">{r.name || key}</CardTitle><Badge className={r.status === 'pass' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30 text-[10px]' : r.status === 'close' ? 'bg-yellow-500/15 text-yellow-300 border-yellow-400/30 text-[10px]' : 'bg-red-500/15 text-red-300 border-red-400/30 text-[10px]'}>{r.status?.toUpperCase() || 'N/A'}</Badge></div></CardHeader><CardContent><div className="grid grid-cols-2 gap-2"><div className="p-2 rounded-md bg-slate-800/50 text-center"><p className="text-lg font-bold text-white">{r.trades || 0}</p><p className="text-[10px] text-slate-400">Trades</p></div><div className="p-2 rounded-md bg-slate-800/50 text-center"><p className="text-lg font-bold text-white">{r.win_rate || 0}%</p><p className="text-[10px] text-slate-400">Win Rate</p></div><div className="p-2 rounded-md bg-slate-800/50 text-center"><p className={`text-lg font-bold ${(r.pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${(r.pnl || 0).toLocaleString()}</p><p className="text-[10px] text-slate-400">P&L ({r.return_pct || 0}%)</p></div><div className="p-2 rounded-md bg-slate-800/50 text-center"><p className="text-lg font-bold text-white">{r.sharpe || 0}</p><p className="text-[10px] text-slate-400">Sharpe</p></div></div></CardContent></Card>;
                })}
              </div>
              {performance.monte_carlo && <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm text-slate-200">Monte Carlo Results</CardTitle></CardHeader><CardContent><div className="grid grid-cols-2 md:grid-cols-4 gap-3">{Object.entries(performance.monte_carlo as Record<string, number | string>).map(([k, v]) => <div key={k} className="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-center"><p className="text-lg font-bold text-white">{typeof v === 'number' ? v.toFixed(1) : v}{typeof v === 'number' && k.includes('return') ? '%' : ''}</p><p className="text-[10px] text-slate-400 capitalize">{k.replace(/_/g, ' ')}</p></div>)}</div></CardContent></Card>}
            </div>}
          </TabsContent>

          {/* CONTROL */}
          <TabsContent value="control" className="mt-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Power className="h-4 w-4 text-emerald-400" />Bot Control</CardTitle></CardHeader><CardContent className="space-y-3">
                <div className="flex gap-2"><Button size="sm" className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs" onClick={handleToggleTrading} disabled={isTrading}><Play className="h-3 w-3 mr-1" />Start</Button><Button size="sm" className="flex-1 bg-red-600 hover:bg-red-700 text-white text-xs" onClick={handleToggleTrading} disabled={!isTrading}><Pause className="h-3 w-3 mr-1" />Stop</Button></div>
                <Button size="sm" variant="outline" className="w-full border-red-500/40 text-red-300 hover:bg-red-500/15 text-xs" onClick={() => setShowEmergency(true)}><AlertTriangle className="h-3 w-3 mr-1" />Emergency Close All</Button>
                <Separator className="bg-slate-700" />
                <div className="flex items-center gap-2"><div className={`w-2 h-2 rounded-full ${isTrading ? 'bg-emerald-400' : 'bg-slate-500'}`} /><span className="text-sm text-slate-200">{isTrading ? 'Trading Active' : 'Idle'}</span></div>
              </CardContent></Card>

              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Settings className="h-4 w-4 text-blue-400" />Settings</CardTitle></CardHeader><CardContent className="space-y-4">
                <div><Label className="text-xs text-slate-300 mb-2 block font-medium">Phase</Label><Select value={currentPhase} onValueChange={() => {}}><SelectTrigger className="bg-slate-800 border-slate-700 text-slate-200 text-xs"><SelectValue /></SelectTrigger><SelectContent className="bg-slate-900 border-slate-700">{(currentFirm?.phases || ['phase1', 'phase2', 'funded']).map(p => <SelectItem key={p} value={p} className="text-slate-200 text-xs capitalize">{p === 'funded' ? 'Funded' : p.replace('phase', 'Phase ')}</SelectItem>)}</SelectContent></Select></div>
                <div><Label className="text-xs text-slate-300 mb-1.5 block font-medium">Risk Per Trade: <span className="text-emerald-400 font-bold">{riskPct}%</span></Label><input type="range" min={0.1} max={2.0} step={0.1} value={riskPct} onChange={e => setRiskPct(parseFloat(e.target.value))} className="w-full h-2 rounded-full bg-slate-700 accent-emerald-400 cursor-pointer" /><div className="flex justify-between text-[10px] text-slate-400 mt-1"><span>0.1%</span><span>2.0%</span></div></div>
                <Separator className="bg-slate-700" />
                <div><Label className="text-xs text-slate-300 mb-1.5 block font-medium">Connection</Label><div className="flex gap-2"><Button size="sm" variant={connectionType === 'metaapi' ? 'default' : 'outline'} onClick={() => { setConnectionType('metaapi'); doToast('MetaAPI Cloud'); }} className={connectionType === 'metaapi' ? 'bg-purple-600 hover:bg-purple-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><Wifi className="h-3 w-3 mr-1" /> MetaAPI</Button><Button size="sm" variant={connectionType === 'mt5' ? 'default' : 'outline'} onClick={() => { setConnectionType('mt5'); doToast('MT5 Local'); }} className={connectionType === 'mt5' ? 'bg-blue-600 hover:bg-blue-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><CircleDot className="h-3 w-3 mr-1" /> MT5 Local</Button></div></div>
                <div><Label className="text-xs text-slate-300 mb-1.5 block font-medium">Trading Mode</Label><div className="flex gap-2"><Button size="sm" variant={tradingMode === 'auto' ? 'default' : 'outline'} onClick={() => { setTradingMode('auto'); doToast('AUTO mode'); }} className={tradingMode === 'auto' ? 'bg-emerald-600 hover:bg-emerald-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><Zap className="h-3 w-3 mr-1" /> Auto</Button><Button size="sm" variant={tradingMode === 'manual' ? 'default' : 'outline'} onClick={() => { setTradingMode('manual'); doToast('MANUAL mode'); }} className={tradingMode === 'manual' ? 'bg-amber-600 hover:bg-amber-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><Hand className="h-3 w-3 mr-1" /> Manual</Button></div></div>
              </CardContent></Card>

              <Card className="bg-slate-900 border-slate-700"><CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Eye className="h-4 w-4 text-yellow-400" />Mode</CardTitle></CardHeader><CardContent className="space-y-4">
                <ToggleSwitch checked={isPaper} onChange={handleTogglePaper} label={isPaper ? 'Paper Trading' : 'Live Trading'} />
                <Separator className="bg-slate-700" />
                <div className="space-y-2 text-sm"><div className="flex justify-between"><span className="text-slate-400">Connected</span><span className={botStatus?.connection === 'connected' ? 'text-emerald-400' : 'text-red-400'}>{botStatus?.connection || 'unknown'}</span></div><div className="flex justify-between"><span className="text-slate-400">Provider</span><span className="text-slate-200">{botStatus?.provider || 'N/A'}</span></div><div className="flex justify-between"><span className="text-slate-400">Active Strategies</span><span className="text-emerald-400">{botStatus?.active_strategies || 0}</span></div><div className="flex justify-between"><span className="text-slate-400">Positions</span><span className="text-slate-200">{positions.length}</span></div></div>
                <Separator className="bg-slate-700" />
                <Button size="sm" className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs" onClick={() => { fetchStatus(); fetchAccount(); fetchPositions(); doToast('Refreshed'); }}><RefreshCw className="h-3 w-3 mr-1" /> Refresh</Button>
              </CardContent></Card>
            </div>
          </TabsContent>

          {/* SETTINGS */}
          <TabsContent value="settings" className="mt-4"><div className="max-w-2xl mx-auto"><CredentialManager /></div></TabsContent>
        </Tabs>
      </main>

      {/* EMERGENCY DIALOG */}
      <Dialog open={showEmergency} onOpenChange={setShowEmergency}>
        <DialogContent className="bg-slate-900 border-red-500/40">
          <DialogHeader><DialogTitle className="text-red-400 flex items-center gap-2"><AlertTriangle className="h-5 w-5" />Emergency Close All</DialogTitle><DialogDescription className="text-slate-400">This will close ALL positions at market price and halt trading. Cannot be undone.</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setShowEmergency(false)} className="border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700">Cancel</Button><Button variant="destructive" onClick={handleEmergency}>Confirm Close All</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
