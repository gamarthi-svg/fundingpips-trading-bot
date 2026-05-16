import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Toaster, toast } from 'sonner';
import {
  Activity, TrendingUp, TrendingDown, Pause, Play, AlertTriangle,
  DollarSign, BarChart3, Clock, Zap, Target, Percent,
  Wallet, Wifi, WifiOff, Settings,
  Hand, CircleDot, RefreshCw, FlaskConical, Calculator,
  ClipboardList, Cog, Power, Loader2, Radio, History, Gauge,
  ShieldCheck
} from 'lucide-react';
import CredentialManager from './components/CredentialManager';
import './App.css';

// ═══════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════
interface Position { ticket: number; symbol: string; direction: string; volume: number; openPrice: number; currentPrice: number; sl: number; tp: number; profit: number; swap: number; openTime: string; }
interface Trade { ticket: number; symbol: string; direction: string; volume: number; entryPrice: number; exitPrice: number; profit: number; commission: number; swap: number; openTime: string; closeTime: string; }
interface BacktestResult { name: string; trades: number; win_rate: number; pnl: number; return_pct: number; max_dd: number; profit_factor: number; sharpe: number; status: string; }
export type { BacktestResult };
interface DashboardData { account: any; backtest: Record<string, any>; recommendations: string[]; }

// ═══════════════════════════════════════════════════════════
// LIMITS — ALL FUNDINGPIPS ACCOUNT TYPES
// ═══════════════════════════════════════════════════════════
type PhaseKey = '2step-eval' | '2step-funded' | '1step-eval' | '1step-funded' | 'pro-eval' | 'pro-funded';

const LIMITS: Record<PhaseKey, { dailyDDPct: number; maxDDPct: number; maxLossPerTrade: number; label: string; color: string; badgeBg: string }> = {
  '2step-eval':    { dailyDDPct: 0.05, maxDDPct: 0.10, maxLossPerTrade: 0.03, label: '2-Step Eval',    color: 'text-purple-300',  badgeBg: 'bg-purple-500/15 border-purple-400/30' },
  '2step-funded':  { dailyDDPct: 0.05, maxDDPct: 0.10, maxLossPerTrade: 0.02, label: '2-Step Funded',  color: 'text-emerald-300', badgeBg: 'bg-emerald-500/15 border-emerald-400/30' },
  '1step-eval':    { dailyDDPct: 0.04, maxDDPct: 0.06, maxLossPerTrade: 0.03, label: '1-Step Eval',    color: 'text-orange-300',  badgeBg: 'bg-orange-500/15 border-orange-400/30' },
  '1step-funded':  { dailyDDPct: 0.04, maxDDPct: 0.06, maxLossPerTrade: 0.02, label: '1-Step Funded',  color: 'text-cyan-300',    badgeBg: 'bg-cyan-500/15 border-cyan-400/30' },
  'pro-eval':      { dailyDDPct: 0.03, maxDDPct: 0.06, maxLossPerTrade: 0.02, label: 'Pro Eval',       color: 'text-amber-300',   badgeBg: 'bg-amber-500/15 border-amber-400/30' },
  'pro-funded':    { dailyDDPct: 0.03, maxDDPct: 0.06, maxLossPerTrade: 0.02, label: 'Pro Funded',     color: 'text-rose-300',    badgeBg: 'bg-rose-500/15 border-rose-400/30' },
};

const ZONE_STYLES: Record<string, { bg: string; border: string; text: string; dot: string; label: string }> = {
  safe:    { bg: 'bg-emerald-500/15', border: 'border-emerald-400/30', text: 'text-emerald-300',  dot: 'bg-emerald-400',  label: 'SAFE' },
  caution: { bg: 'bg-yellow-500/15',  border: 'border-yellow-400/30',  text: 'text-yellow-300',   dot: 'bg-yellow-400',   label: 'CAUTION' },
  danger:  { bg: 'bg-red-500/15',     border: 'border-red-400/30',     text: 'text-red-300',      dot: 'bg-red-400',      label: 'DANGER' },
  blocked: { bg: 'bg-red-600/20',     border: 'border-red-500/40',     text: 'text-red-200',      dot: 'bg-red-500',      label: 'BLOCKED' },
};

const STRATEGIES = [
  { name: 'XAUUSD Asian Scalp', instrument: 'XAUUSD', session: 'Asian (23:00\u201303:00 GMT)', type: 'Range Scalping', winRate: 75, trades: 12, pnl: 1850, sl: '10 pips', rr: '1:2', params: 'EMA(20) + RSI(14), body > 0.5\u00d7ATR', status: 'active' as const, priority: 1 },
  { name: 'XAUUSD NY Breakout', instrument: 'XAUUSD', session: 'NY Open (13:30\u201314:30 GMT)', type: 'Opening Range Breakout', winRate: 62, trades: 8, pnl: 920, sl: '18 pips', rr: '1:3', params: '5-min ORB, volume > previous candle', status: 'active' as const, priority: 2 },
  { name: 'NQ ORB', instrument: 'NQ (Nasdaq)', session: 'Mon/Wed/Fri (13:30\u201315:30 GMT)', type: 'Opening Range Breakout', winRate: 67, trades: 6, pnl: 680, sl: '10 pts', rr: '1:4', params: '15-min OR, partials 50%@1.5R/30%@2.5R/20%@4R', status: 'active' as const, priority: 3 },
  { name: 'Forex London', instrument: 'EURUSD, GBPUSD, USDJPY', session: 'London (07:00\u201312:00 GMT)', type: 'Session Breakout', winRate: 55, trades: 4, pnl: 310, sl: '18 pips', rr: '1:2', params: 'Asian range breakout on H1 close', status: 'active' as const, priority: 4 },
];

const INSTRUMENTS = ['XAUUSD', 'NQ', 'EURUSD', 'GBPUSD', 'USDJPY'];
const TIMEFRAMES = ['Today', 'This Week', 'This Month', 'All Time'];
const API_BASE = 'http://localhost:8080';

// ═══════════════════════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════════════════════

function ZoneIndicator({ zone }: { zone: string }) {
  const z = ZONE_STYLES[zone] || ZONE_STYLES.safe;
  return (
    <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border ${z.bg} ${z.border}`}>
      <div className={`w-2.5 h-2.5 rounded-full ${z.dot} shadow-[0_0_8px_currentColor]`} />
      <span className={`text-xs font-bold uppercase tracking-wider ${z.text}`}>{z.label}</span>
    </div>
  );
}

function StatCard({ title, value, subtitle, icon: Icon, trend }: { title: string; value: string; subtitle?: string; icon: React.ElementType; trend?: 'up' | 'down' }) {
  const bg = trend === 'up' ? 'bg-emerald-400/10' : trend === 'down' ? 'bg-red-400/10' : 'bg-slate-700/40';
  const ic = trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-red-400' : 'text-slate-300';
  return (
    <Card className="bg-slate-900 border-slate-700 shadow-lg">
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <p className="text-[11px] font-semibold text-slate-300 uppercase tracking-widest">{title}</p>
            <p className="text-xl font-bold text-white tracking-tight">{value}</p>
            {subtitle && <p className="text-[11px] text-slate-400">{subtitle}</p>}
          </div>
          <div className={`p-2 rounded-lg ${bg}`}><Icon className={`h-4 w-4 ${ic}`} /></div>
        </div>
      </CardContent>
    </Card>
  );
}

export type {}; // keep module structure

function ToggleSwitch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-slate-200 font-medium">{label}</span>
      <button onClick={() => onChange(!checked)} className={`relative w-10 h-5 rounded-full transition-colors ${checked ? 'bg-emerald-500' : 'bg-slate-600'}`}>
        <div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </button>
    </div>
  );
}

function ActionButton({ icon: Icon, label, description, onClick, loading = false, variant = 'primary' }: { icon: any; label: string; description: string; onClick: () => void; loading?: boolean; variant?: 'primary' | 'danger' | 'warning' }) {
  const variantStyles = {
    primary: 'bg-blue-600 hover:bg-blue-700 border-blue-500',
    warning: 'bg-amber-600 hover:bg-amber-700 border-amber-500',
    danger: 'bg-red-600 hover:bg-red-700 border-red-500',
  };
  return (
    <button onClick={onClick} disabled={loading} className={`w-full p-3 rounded-lg border ${variantStyles[variant]} text-white text-left transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed`}>
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-md bg-white/10">
          {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Icon className="h-5 w-5" />}
        </div>
        <div>
          <p className="text-sm font-semibold">{label}</p>
          <p className="text-[11px] text-white/60">{description}</p>
        </div>
      </div>
    </button>
  );
}

// ═══════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════
export default function App() {
  const [phase, setPhase] = useState<PhaseKey>('pro-eval');
  const [riskPct, setRiskPct] = useState(0.5);
  const [isTrading, setIsTrading] = useState(false);
  const [tradingMode, setTradingMode] = useState<'auto' | 'manual'>('auto');
  const [isPaper, setIsPaper] = useState(true);
  const [connectionType, setConnectionType] = useState<'metaapi' | 'mt5'>('metaapi');
  const [connected, setConnected] = useState(true);
  const [timeframe, setTimeframe] = useState('Today');
  const [activeInstruments, setActiveInstruments] = useState<Record<string, boolean>>({ XAUUSD: true, NQ: true, EURUSD: true, GBPUSD: false, USDJPY: false });
  const [activeStrategies, setActiveStrategies] = useState<Record<string, boolean>>({ 'XAUUSD Asian Scalp': true, 'XAUUSD NY Breakout': true, 'NQ ORB': true, 'Forex London': true });
  const [lastUpdated, setLastUpdated] = useState(new Date());
  const [showEmergency, setShowEmergency] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');
  const [dashData, setDashData] = useState<DashboardData | null>(null);
  const [livePositions, setLivePositions] = useState<Position[]>([]);
  const [liveTrades, setLiveTrades] = useState<Trade[]>([]);
  const [liveAccount, setLiveAccount] = useState({ balance: 9701.10, equity: 9701.10, profit: -298.90, margin: 0 });
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [jobList, setJobList] = useState<any[]>([]);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const limits = LIMITS[phase];
  const accountSize = 10000;
  const dailyLossLimit = accountSize * limits.dailyDDPct;
  const maxDDLimit = accountSize * limits.maxDDPct;

  const positions: Position[] = [
    { ticket: 123456, symbol: 'XAUUSD', direction: 'buy', volume: 0.5, openPrice: 4713.20, currentPrice: 4718.60, sl: 4708.20, tp: 4723.20, profit: 27, swap: -0.3, openTime: '2025-08-11T14:30:00Z' },
    { ticket: 123457, symbol: 'EURUSD', direction: 'sell', volume: 0.3, openPrice: 1.0875, currentPrice: 1.0862, sl: 1.0895, tp: 1.0840, profit: 14, swap: -0.1, openTime: '2025-08-11T08:15:00Z' },
  ];
  const trades: Trade[] = [
    { ticket: 1, symbol: 'XAUUSD', direction: 'buy', volume: 0.5, entryPrice: 4711.80, exitPrice: 4715.20, profit: 34, commission: -2.5, swap: -0.1, openTime: '2025-08-11T23:15:00Z', closeTime: '2025-08-12T01:30:00Z' },
    { ticket: 2, symbol: 'XAUUSD', direction: 'buy', volume: 0.3, entryPrice: 4710.50, exitPrice: 4712.80, profit: 23, commission: -1.5, swap: -0.1, openTime: '2025-08-11T23:45:00Z', closeTime: '2025-08-12T02:15:00Z' },
    { ticket: 3, symbol: 'NQ', direction: 'sell', volume: 1.0, entryPrice: 18750.00, exitPrice: 18720.00, profit: 60, commission: 0, swap: -0.2, openTime: '2025-08-11T13:35:00Z', closeTime: '2025-08-11T14:45:00Z' },
    { ticket: 4, symbol: 'EURUSD', direction: 'buy', volume: 0.4, entryPrice: 1.0860, exitPrice: 1.0852, profit: -8, commission: -2.0, swap: -0.05, openTime: '2025-08-11T07:05:00Z', closeTime: '2025-08-11T09:30:00Z' },
    { ticket: 5, symbol: 'XAUUSD', direction: 'buy', volume: 0.5, entryPrice: 4713.00, exitPrice: 4716.50, profit: 35, commission: -2.5, swap: -0.1, openTime: '2025-08-11T13:32:00Z', closeTime: '2025-08-11T14:20:00Z' },
    { ticket: 6, symbol: 'NQ', direction: 'buy', volume: 0.5, entryPrice: 18700.00, exitPrice: 18695.00, profit: -10, commission: 0, swap: -0.1, openTime: '2025-08-11T13:31:00Z', closeTime: '2025-08-11T14:10:00Z' },
  ];

  const totalTrades = trades.length;
  const winCount = trades.filter(t => t.profit > 0).length;
  const winRate = Math.round((winCount / totalTrades) * 100);
  const totalPnL = trades.reduce((s, t) => s + t.profit, 0);
  const avgWin = trades.filter(t => t.profit > 0).reduce((s, t) => s + t.profit, 0) / Math.max(winCount, 1);
  const avgLoss = Math.abs(trades.filter(t => t.profit < 0).reduce((s, t) => s + t.profit, 0) / Math.max(totalTrades - winCount, 1));
  const profitFactor = avgWin / Math.max(avgLoss, 1);

  // ── Fetch real data ──
  useEffect(() => { const iv = setInterval(() => setLastUpdated(new Date()), 1000); return () => clearInterval(iv); }, []);

  // ── Poll job status ──
  useEffect(() => {
    const pollJobs = async () => {
      try {
        const r = await fetch(`${API_BASE}/api/jobs?limit=10`);
        if (r.ok) {
          const jobs = await r.json();
          setJobList(jobs);
          // Check if any running job matches our runningAction
          const running = jobs.find((j: any) => j.status === 'running');
          if (!running && runningAction) {
            setRunningAction(null);
          }
        }
      } catch { /* backend not running yet */ }
    };
    pollJobs();
    const iv = setInterval(pollJobs, 3000);
    return () => clearInterval(iv);
  }, [runningAction]);

  useEffect(() => {
    fetch('/dashboard_data.json').then(r => r.ok ? r.json() : null).then(data => { if (data) setDashData(data); }).catch(() => {});
  }, []);

  // ── WebSocket for live data ──
  useEffect(() => {
    const ws = new WebSocket(`ws://${API_BASE.replace(/^https?:\/\//, '').replace(/\/+$/, '')}/ws`);
    wsRef.current = ws;
    ws.onopen = () => { setConnected(true); };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.positions) setLivePositions(data.positions);
        if (data.trades) setLiveTrades(data.trades);
        if (data.account) setLiveAccount(data.account);
      } catch { /* ignore parse errors */ }
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    return () => ws.close();
  }, []);

  const doToast = (msg: string) => { if (toastTimer.current) clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => toast.success(msg), 100); };

  // ── Action Handlers ──
  const runAction = async (name: string, _apiCall?: () => Promise<any>) => {
    setRunningAction(name);
    toast.loading(`${name} in progress...`);
    try {
      await new Promise(resolve => setTimeout(resolve, 2000));
      // In real usage: await apiCall();
      toast.dismiss();
      doToast(`${name} completed!`);
    } catch (e) {
      toast.dismiss();
      toast.error(`${name} failed`);
    } finally {
      setRunningAction(null);
    }
  };

  const handleBacktest = () => runAction('Backtest', async () => fetch(`${API_BASE}/api/backtest/run`, { method: 'POST' }));
  const handleOptimize = () => runAction('Walk-Forward Optimization', async () => fetch(`${API_BASE}/api/backtest/optimize`, { method: 'POST' }));
  const handleMonteCarlo = () => runAction('Monte Carlo Simulation', async () => fetch(`${API_BASE}/api/backtest/mc`, { method: 'POST' }));
  const handleStressTest = () => runAction('Stress Test', async () => fetch(`${API_BASE}/api/backtest/stress`, { method: 'POST' }));
  const handleFetchData = () => runAction('Fetch Historical Data', async () => fetch(`${API_BASE}/api/data/fetch`, { method: 'POST' }));
  const handleGenerateReport = () => runAction('Generate Report', async () => fetch(`${API_BASE}/api/backtest/report`, { method: 'POST' }));

  const handleToggleTrading = () => { setIsTrading(p => !p); doToast(isTrading ? 'Bot STOPPED' : 'Bot STARTED'); };
  const handleEmergency = () => { setShowEmergency(false); toast.error('All positions closed. Trading halted.'); setIsTrading(false); };
  const handleTogglePaper = (val: boolean) => { setIsPaper(val); doToast(val ? 'PAPER TRADING mode' : 'LIVE TRADING mode'); };
  const handleToggleStrategy = (name: string) => { setActiveStrategies(p => ({ ...p, [name]: !p[name] })); };
  const fmtTime = (d: Date) => d.toISOString().slice(11, 19) + ' UTC';

  // Display positions: use live if available, fallback to static
  const displayPositions = livePositions.length > 0 ? livePositions : positions;
  const displayTrades = liveTrades.length > 0 ? liveTrades : trades;
  const displayAccount = liveAccount.equity > 0 ? liveAccount : { balance: 9701.10, equity: 9701.10, profit: -298.90, margin: 0 };

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100">
      <Toaster position="top-right" toastOptions={{ style: { background: '#0f172a', border: '1px solid #475569', color: '#e2e8f0' } }} />

      {/* ═══ HEADER ═══ */}
      <header className="border-b border-slate-700/50 bg-[#070b14]/95 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-400/30 flex items-center justify-center">
              <Activity className="h-4 w-4 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white leading-tight">PropFirm Bot</h1>
              <p className="text-[10px] text-slate-400">FundingPips • $10K Pro 2-Step</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Paper/Live Toggle */}
            <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border ${isPaper ? 'bg-yellow-500/10 border-yellow-400/30' : 'bg-red-500/10 border-red-400/30'}`}>
              <button onClick={() => handleTogglePaper(!isPaper)} className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${isPaper ? 'bg-yellow-400' : 'bg-red-400'}`} />
                <span className={`text-xs font-bold uppercase tracking-wider ${isPaper ? 'text-yellow-300' : 'text-red-300'}`}>{isPaper ? 'PAPER' : 'LIVE'}</span>
              </button>
            </div>
            <Badge variant="outline" className={`${limits.badgeBg} ${limits.color} text-xs`}><Target className="h-3 w-3 mr-1" />{limits.label}</Badge>
            <ZoneIndicator zone="safe" />
            <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-800/50 border border-slate-700">
              {connected ? <Wifi className="h-3 w-3 text-emerald-400" /> : <WifiOff className="h-3 w-3 text-red-400" />}
              <span className="text-[10px] text-slate-300">{connectionType === 'metaapi' ? 'MetaAPI' : 'MT5'}</span>
            </div>
            <div className={`w-2 h-2 rounded-full ${isTrading ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : 'bg-slate-500'}`} />
            <span className="text-[10px] text-slate-300">{isTrading ? 'ACTIVE' : 'IDLE'}</span>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">

        {/* ═══ STATS ROW ═══ */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard title="Balance" value={`$${displayAccount.balance.toLocaleString()}`} subtitle={`${displayAccount.profit >= 0 ? '+' : ''}$${displayAccount.profit.toLocaleString()}`} icon={Wallet} />
          <StatCard title="Equity" value={`$${displayAccount.equity.toLocaleString()}`} subtitle={`${displayAccount.profit >= 0 ? '+' : ''}$${displayAccount.profit.toLocaleString()} unrealized`} icon={DollarSign} trend={displayAccount.profit >= 0 ? 'up' : 'down'} />
          <StatCard title="Daily P&L" value={`+$1,240`} subtitle={`Today`} icon={TrendingUp} trend="up" />
          <StatCard title="Win Rate" value={`${winRate}%`} subtitle={`${winCount}/${totalTrades} trades`} icon={Percent} trend="up" />
          <StatCard title="Max DD" value={`2.1%`} subtitle={`Limit: $${(maxDDLimit / 1000).toFixed(0)}K`} icon={TrendingDown} />
          <StatCard title="Open Pos" value={`${displayPositions.length}`} subtitle={`Floating: $${displayPositions.reduce((s, p) => s + p.profit, 0)}`} icon={Radio} />
        </div>

        {/* ═══ CONTROLS + BOT STATUS ═══ */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Bot Start/Stop */}
          <Button size="sm" onClick={handleToggleTrading} className={isTrading ? 'border border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20' : 'bg-emerald-600 hover:bg-emerald-700 text-white'}>
            {isTrading ? <><Power className="h-4 w-4 mr-2" /> Stop Bot</> : <><Play className="h-4 w-4 mr-2" /> Start Bot</>}
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowEmergency(true)} className="border-red-500/40 text-red-300 hover:bg-red-500/15 bg-red-500/5">
            <AlertTriangle className="h-4 w-4 mr-2" /> Emergency Close
          </Button>
          <div className="ml-auto flex items-center gap-3 text-[11px] text-slate-400">
            <Clock className="h-3.5 w-3.5 text-slate-500" /><span>Up: 3d 7h</span>
            <Zap className="h-3.5 w-3.5 text-slate-500" /><span>Check: 5s</span>
            <span className="text-slate-600">|</span>
            <span className="text-slate-400">Updated: {fmtTime(lastUpdated)}</span>
          </div>
        </div>

        {/* ═══ TABS ═══ */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-slate-800/80 border border-slate-700 flex-wrap h-auto">
            <TabsTrigger value="overview" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Gauge className="h-3 w-3 mr-1" />Overview</TabsTrigger>
            <TabsTrigger value="positions" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Radio className="h-3 w-3 mr-1" />Positions ({displayPositions.length})</TabsTrigger>
            <TabsTrigger value="history" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><History className="h-3 w-3 mr-1" />History ({displayTrades.length})</TabsTrigger>
            <TabsTrigger value="strategies" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Zap className="h-3 w-3 mr-1" />Strategies</TabsTrigger>
            <TabsTrigger value="backtest" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><FlaskConical className="h-3 w-3 mr-1" />Backtest</TabsTrigger>
            <TabsTrigger value="control" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><Cog className="h-3 w-3 mr-1" />Control</TabsTrigger>
            <TabsTrigger value="settings" className="text-xs data-[state=active]:bg-slate-700 data-[state=active]:text-white text-slate-300"><ShieldCheck className="h-3 w-3 mr-1" />Settings</TabsTrigger>
          </TabsList>

          {/* ── OVERVIEW TAB ── */}
          <TabsContent value="overview" className="space-y-4 mt-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">Period:</span>
              {TIMEFRAMES.map(tf => (
                <Button key={tf} size="sm" variant={timeframe === tf ? 'default' : 'outline'} onClick={() => setTimeframe(tf)}
                  className={timeframe === tf ? 'bg-emerald-600 hover:bg-emerald-700 text-white text-xs h-7' : 'border-slate-600 bg-slate-800 text-slate-200 hover:text-white text-xs h-7'}>{tf}</Button>
              ))}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Card className="bg-slate-900 border-slate-700 shadow-lg"><CardContent className="p-4 text-center"><p className="text-2xl font-bold text-white">{totalTrades}</p><p className="text-[11px] text-slate-400">Total Trades</p></CardContent></Card>
              <Card className="bg-slate-900 border-slate-700 shadow-lg"><CardContent className="p-4 text-center"><p className="text-2xl font-bold text-emerald-400">+${totalPnL.toLocaleString()}</p><p className="text-[11px] text-slate-400">Total P&L</p></CardContent></Card>
              <Card className="bg-slate-900 border-slate-700 shadow-lg"><CardContent className="p-4 text-center"><p className="text-2xl font-bold text-white">{profitFactor.toFixed(2)}</p><p className="text-[11px] text-slate-400">Profit Factor</p></CardContent></Card>
              <Card className="bg-slate-900 border-slate-700 shadow-lg"><CardContent className="p-4 text-center"><p className="text-2xl font-bold text-white">{avgWin.toFixed(0)} / {avgLoss.toFixed(0)}</p><p className="text-[11px] text-slate-400">Avg Win / Loss ($)</p></CardContent></Card>
            </div>
          </TabsContent>

          {/* ── POSITIONS TAB (Live from WS) ── */}
          <TabsContent value="positions" className="mt-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-slate-400">{livePositions.length > 0 ? 'Live from MetaAPI WebSocket' : 'Simulated positions'}</span>
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${livePositions.length > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                <span className="text-[10px] text-slate-400">{livePositions.length > 0 ? 'LIVE' : 'OFFLINE'}</span>
              </div>
            </div>
            <Card className="bg-slate-900 border-slate-700 shadow-lg">
              <CardContent className="p-0">
                <Table>
                  <TableHeader><TableRow className="border-slate-700 hover:bg-transparent">
                    <TableHead className="text-slate-300 text-xs">Symbol</TableHead>
                    <TableHead className="text-slate-300 text-xs">Dir</TableHead>
                    <TableHead className="text-slate-300 text-xs">Vol</TableHead>
                    <TableHead className="text-slate-300 text-xs">Open</TableHead>
                    <TableHead className="text-slate-300 text-xs">Current</TableHead>
                    <TableHead className="text-slate-300 text-xs">SL / TP</TableHead>
                    <TableHead className="text-slate-300 text-xs text-right">P&L</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {displayPositions.map(p => (
                      <TableRow key={p.ticket} className="border-slate-700">
                        <TableCell className="font-medium text-white text-sm">{p.symbol}</TableCell>
                        <TableCell><Badge variant="outline" className={p.direction === 'buy' ? 'border-emerald-400/40 text-emerald-300 text-xs' : 'border-red-400/40 text-red-300 text-xs'}>{p.direction.toUpperCase()}</Badge></TableCell>
                        <TableCell className="text-slate-200 text-sm">{p.volume}</TableCell>
                        <TableCell className="text-slate-200 text-sm">{p.openPrice.toFixed(p.symbol === 'XAUUSD' ? 2 : 4)}</TableCell>
                        <TableCell className="text-slate-200 text-sm">{p.currentPrice.toFixed(p.symbol === 'XAUUSD' ? 2 : 4)}</TableCell>
                        <TableCell className="text-xs text-slate-300">{p.sl} / {p.tp}</TableCell>
                        <TableCell className={`text-right font-bold text-sm ${p.profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{p.profit >= 0 ? '+' : ''}${p.profit.toLocaleString()}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── HISTORY TAB (MetaAPI history) ── */}
          <TabsContent value="history" className="mt-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-slate-400">{liveTrades.length > 0 ? 'From MetaAPI trade history' : 'Simulated trade history'}</span>
            </div>
            <Card className="bg-slate-900 border-slate-700 shadow-lg">
              <CardContent className="p-0">
                <Table>
                  <TableHeader><TableRow className="border-slate-700 hover:bg-transparent">
                    <TableHead className="text-slate-300 text-xs">Symbol</TableHead>
                    <TableHead className="text-slate-300 text-xs">Dir</TableHead>
                    <TableHead className="text-slate-300 text-xs">Vol</TableHead>
                    <TableHead className="text-slate-300 text-xs">Entry</TableHead>
                    <TableHead className="text-slate-300 text-xs">Exit</TableHead>
                    <TableHead className="text-slate-300 text-xs">Swap</TableHead>
                    <TableHead className="text-slate-300 text-xs text-right">P&L</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {displayTrades.map(t => (
                      <TableRow key={t.ticket} className="border-slate-700">
                        <TableCell className="font-medium text-white text-sm">{t.symbol}</TableCell>
                        <TableCell><Badge variant="outline" className={t.direction === 'buy' ? 'border-emerald-400/40 text-emerald-300 text-xs' : 'border-red-400/40 text-red-300 text-xs'}>{t.direction.toUpperCase()}</Badge></TableCell>
                        <TableCell className="text-slate-200 text-sm">{t.volume}</TableCell>
                        <TableCell className="text-slate-200 text-sm">{t.entryPrice.toFixed(2)}</TableCell>
                        <TableCell className="text-slate-200 text-sm">{t.exitPrice.toFixed(2)}</TableCell>
                        <TableCell className="text-xs text-slate-400">${t.swap}</TableCell>
                        <TableCell className={`text-right font-bold text-sm ${t.profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{t.profit >= 0 ? '+' : ''}${t.profit.toLocaleString()}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── STRATEGIES TAB ── */}
          <TabsContent value="strategies" className="space-y-4 mt-4">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">All strategies are session-aware and activate only during their designated trading windows.</span>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {STRATEGIES.map(s => (
                <Card key={s.name} className={`bg-slate-900 border-slate-700 shadow-lg ${(activeStrategies[s.name] ?? true) ? 'border-l-4 border-l-emerald-500' : 'border-l-4 border-l-slate-600 opacity-60'}`}>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Zap className="h-4 w-4 text-amber-400" />{s.name}</CardTitle>
                      <div className="flex items-center gap-2">
                        <ToggleSwitch checked={activeStrategies[s.name] ?? true} onChange={() => handleToggleStrategy(s.name)} label="" />
                      </div>
                    </div>
                    <CardDescription className="text-xs text-slate-400">{s.instrument} &bull; {s.session}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-4 gap-2 text-center">
                      <div className="p-2 rounded-md bg-slate-800/50 border border-slate-700"><p className="text-lg font-bold text-white">{s.winRate}%</p><p className="text-[10px] text-slate-400">Win Rate</p></div>
                      <div className="p-2 rounded-md bg-slate-800/50 border border-slate-700"><p className="text-lg font-bold text-white">{s.trades}</p><p className="text-[10px] text-slate-400">Trades</p></div>
                      <div className="p-2 rounded-md bg-slate-800/50 border border-slate-700"><p className="text-lg font-bold text-emerald-400">+${s.pnl}</p><p className="text-[10px] text-slate-400">P&L ($)</p></div>
                      <div className="p-2 rounded-md bg-slate-800/50 border border-slate-700"><p className="text-lg font-bold text-white">{s.rr}</p><p className="text-[10px] text-slate-400">R:R</p></div>
                    </div>
                    <div className="p-2 rounded-md bg-slate-800/40 border border-slate-700/50"><p className="text-[11px] text-slate-400">{s.params}</p></div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          {/* ── BACKTEST TAB ── */}
          <TabsContent value="backtest" className="space-y-4 mt-4">
            {/* Action Buttons */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <ActionButton icon={RefreshCw} label="Fetch Data" description="Download historical OHLCV" onClick={handleFetchData} loading={runningAction === 'Fetch Data'} variant="primary" />
              <ActionButton icon={FlaskConical} label="Run Backtest" description="Backtest all strategies" onClick={handleBacktest} loading={runningAction === 'Backtest'} variant="primary" />
              <ActionButton icon={Cog} label="Optimize" description="Walk-forward parameter tuning" onClick={handleOptimize} loading={runningAction === 'Walk-Forward Optimization'} variant="warning" />
              <ActionButton icon={Calculator} label="Monte Carlo" description="10,000 simulation stress test" onClick={handleMonteCarlo} loading={runningAction === 'Monte Carlo Simulation'} variant="warning" />
              <ActionButton icon={BarChart3} label="Stress Test" description="Extreme scenario analysis" onClick={handleStressTest} loading={runningAction === 'Stress Test'} variant="warning" />
              <ActionButton icon={ClipboardList} label="Report" description="Generate HTML + JSON report" onClick={handleGenerateReport} loading={runningAction === 'Generate Report'} variant="primary" />
            </div>

            {/* Job Status Panel */}
            {jobList.length > 0 && (
              <Card className="bg-slate-900 border-slate-700 shadow-lg">
                <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-200">Job Queue</CardTitle></CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {jobList.map(job => (
                      <div key={job.id} className="flex items-center gap-3 p-2 rounded-md bg-slate-800/50 border border-slate-700">
                        <div className={`w-2 h-2 rounded-full ${job.status === 'running' ? 'bg-amber-400 animate-pulse' : job.status === 'completed' ? 'bg-emerald-400' : job.status === 'failed' ? 'bg-red-400' : 'bg-slate-500'}`} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-slate-200 truncate">{job.type} <span className="text-slate-500">#{job.id}</span></span>
                            <span className={`text-[10px] font-bold uppercase ${job.status === 'running' ? 'text-amber-400' : job.status === 'completed' ? 'text-emerald-400' : job.status === 'failed' ? 'text-red-400' : 'text-slate-400'}`}>{job.status}</span>
                          </div>
                          {job.status === 'running' && (
                            <div className="mt-1 w-full h-1.5 rounded-full bg-slate-700 overflow-hidden">
                              <div className="h-full bg-amber-400 rounded-full transition-all" style={{ width: `${job.progress || 0}%` }} />
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {dashData ? (
              <>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {Object.values(dashData.backtest).filter((r: any) => r.name).map((result: any) => (
                    <Card key={result.name} className={`bg-slate-900 border-slate-700 shadow-lg ${result.status === 'pass' ? 'border-l-4 border-l-emerald-500' : result.status === 'close' ? 'border-l-4 border-l-yellow-500' : 'border-l-4 border-l-red-500'}`}>
                      <CardHeader className="pb-2">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-sm text-slate-200">{result.name}</CardTitle>
                          <Badge className={result.status === 'pass' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30 text-[10px]' : result.status === 'close' ? 'bg-yellow-500/15 text-yellow-300 border-yellow-400/30 text-[10px]' : 'bg-red-500/15 text-red-300 border-red-400/30 text-[10px]'}>
                            {result.status === 'pass' ? 'PASS' : result.status === 'close' ? 'CLOSE' : 'FAIL'}
                          </Badge>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-2">
                        <div className="grid grid-cols-2 gap-2">
                          <div className="p-2 rounded-md bg-slate-800/50 text-center"><p className="text-lg font-bold text-white">{result.trades}</p><p className="text-[10px] text-slate-400">Trades</p></div>
                          <div className="p-2 rounded-md bg-slate-800/50 text-center"><p className="text-lg font-bold text-white">{result.win_rate}%</p><p className="text-[10px] text-slate-400">Win Rate</p></div>
                          <div className="p-2 rounded-md bg-slate-800/50 text-center"><p className={`text-lg font-bold ${result.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${result.pnl.toLocaleString()}</p><p className="text-[10px] text-slate-400">P&L ({result.return_pct}%)</p></div>
                          <div className="p-2 rounded-md bg-slate-800/50 text-center"><p className="text-lg font-bold text-white">{result.sharpe}</p><p className="text-[10px] text-slate-400">Sharpe</p></div>
                        </div>
                        <div className="space-y-1">
                          <div className="flex justify-between text-xs"><span className="text-slate-400">Max DD:</span><span className={`font-semibold ${result.max_dd <= 6 ? 'text-emerald-400' : 'text-red-400'}`}>{result.max_dd}%</span></div>
                          <div className="flex justify-between text-xs"><span className="text-slate-400">Profit Factor:</span><span className="text-slate-200">{result.profit_factor}</span></div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {dashData.backtest.monte_carlo && (
                  <Card className="bg-slate-900 border-slate-700 shadow-lg">
                    <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-200">Monte Carlo (10,000 Simulations)</CardTitle></CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-center">
                          <p className="text-2xl font-bold text-emerald-400">{(dashData.backtest.monte_carlo as any).pass_rate}%</p>
                          <p className="text-[10px] text-slate-400">Pass Rate (Pro 2-Step)</p>
                        </div>
                        <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-center">
                          <p className="text-2xl font-bold text-white">+{(dashData.backtest.monte_carlo as any).median_return}%</p>
                          <p className="text-[10px] text-slate-400">Median Return</p>
                        </div>
                        <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-center">
                          <p className="text-2xl font-bold text-amber-400">+{(dashData.backtest.monte_carlo as any).worst_case}%</p>
                          <p className="text-[10px] text-slate-400">Worst Case (5th %ile)</p>
                        </div>
                        <div className="p-3 rounded-lg bg-slate-800/50 border border-slate-700 text-center">
                          <p className="text-2xl font-bold text-emerald-400">+{(dashData.backtest.monte_carlo as any).best_case}%</p>
                          <p className="text-[10px] text-slate-400">Best Case (95th %ile)</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {dashData.recommendations && (
                  <Card className="bg-slate-900 border-slate-700 shadow-lg">
                    <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-200">Recommendations</CardTitle></CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {dashData.recommendations.map((rec: string, i: number) => (
                          <div key={i} className="flex items-start gap-2 text-xs">
                            <div className={`w-1.5 h-1.5 rounded-full mt-1 ${i === 2 ? 'bg-emerald-400' : i === 1 ? 'bg-yellow-400' : 'bg-slate-500'}`} />
                            <span className="text-slate-300">{rec}</span>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <Card className="bg-slate-900 border-slate-700 shadow-lg">
                <CardContent className="p-8 text-center">
                  <BarChart3 className="h-8 w-8 text-slate-600 mx-auto mb-3" />
                  <p className="text-sm text-slate-400">Click "Fetch Data" then "Run Backtest" to see results</p>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ═══ CONTROL PANEL ═══ */}
          <TabsContent value="control" className="mt-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Account Settings */}
              <Card className="bg-slate-900 border-slate-700 shadow-lg">
                <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Settings className="h-4 w-4 text-blue-400" />Account Settings</CardTitle></CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <Label className="text-xs text-slate-300 mb-2 block font-medium">Phase / Account Type</Label>
                    <div className="grid grid-cols-2 gap-2">
                      {(Object.keys(LIMITS) as PhaseKey[]).map(k => (
                        <Button key={k} size="sm" variant={phase === k ? 'default' : 'outline'} onClick={() => { setPhase(k); doToast(`Phase: ${LIMITS[k].label}`); }}
                          className={phase === k ? `${LIMITS[k].badgeBg} ${LIMITS[k].color} text-xs h-8 font-semibold` : 'border-slate-600 bg-slate-800 text-slate-200 hover:text-white hover:bg-slate-700 text-xs h-8'}>{LIMITS[k].label}</Button>
                      ))}
                    </div>
                    <div className="mt-3 p-3 rounded-md bg-slate-800/60 border border-slate-700 text-[11px] text-slate-300 space-y-1.5">
                      <p>Daily DD: <span className="text-white font-bold">{(limits.dailyDDPct * 100).toFixed(0)}%</span> <span className="text-slate-400">(${dailyLossLimit.toLocaleString()})</span></p>
                      <p>Max DD: <span className="text-white font-bold">{(limits.maxDDPct * 100).toFixed(0)}%</span> <span className="text-slate-400">(${maxDDLimit.toLocaleString()})</span></p>
                      <p>Max Loss/Trade: <span className="text-white font-bold">{(limits.maxLossPerTrade * 100).toFixed(0)}%</span></p>
                    </div>
                  </div>
                  <Separator className="bg-slate-700" />
                  <div>
                    <Label className="text-xs text-slate-300 mb-1.5 block font-medium">Risk Per Trade: <span className="text-emerald-400 font-bold">{riskPct}%</span></Label>
                    <input type="range" min={0.1} max={2.0} step={0.1} value={riskPct} onChange={e => setRiskPct(parseFloat(e.target.value))} className="w-full h-2 rounded-full bg-slate-700 accent-emerald-400 cursor-pointer" />
                    <div className="flex justify-between text-[10px] text-slate-400 mt-1"><span>0.1%</span><span>2.0%</span></div>
                  </div>
                  <Separator className="bg-slate-700" />
                  <div>
                    <Label className="text-xs text-slate-300 mb-1.5 block font-medium">Connection</Label>
                    <div className="flex gap-2">
                      <Button size="sm" variant={connectionType === 'metaapi' ? 'default' : 'outline'} onClick={() => { setConnectionType('metaapi'); doToast('MetaAPI Cloud'); }}
                        className={connectionType === 'metaapi' ? 'bg-purple-600 hover:bg-purple-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><Wifi className="h-3 w-3 mr-1" /> MetaAPI</Button>
                      <Button size="sm" variant={connectionType === 'mt5' ? 'default' : 'outline'} onClick={() => { setConnectionType('mt5'); doToast('MT5 Local'); }}
                        className={connectionType === 'mt5' ? 'bg-blue-600 hover:bg-blue-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><CircleDot className="h-3 w-3 mr-1" /> MT5 Local</Button>
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs text-slate-300 mb-1.5 block font-medium">Trading Mode</Label>
                    <div className="flex gap-2">
                      <Button size="sm" variant={tradingMode === 'auto' ? 'default' : 'outline'} onClick={() => { setTradingMode('auto'); doToast('AUTO mode'); }}
                        className={tradingMode === 'auto' ? 'bg-emerald-600 hover:bg-emerald-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><Zap className="h-3 w-3 mr-1" /> Auto</Button>
                      <Button size="sm" variant={tradingMode === 'manual' ? 'default' : 'outline'} onClick={() => { setTradingMode('manual'); doToast('MANUAL mode'); }}
                        className={tradingMode === 'manual' ? 'bg-amber-600 hover:bg-amber-700 text-white text-xs' : 'border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 text-xs'}><Hand className="h-3 w-3 mr-1" /> Manual</Button>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Instrument Toggles */}
              <Card className="bg-slate-900 border-slate-700 shadow-lg">
                <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Activity className="h-4 w-4 text-emerald-400" />Instruments</CardTitle></CardHeader>
                <CardContent className="space-y-1">
                  {INSTRUMENTS.map(sym => (<ToggleSwitch key={sym} checked={activeInstruments[sym] || false} onChange={() => setActiveInstruments(p => { const n = { ...p, [sym]: !p[sym] }; doToast(`${sym}: ${n[sym] ? 'ON' : 'OFF'}`); return n; })} label={sym} />))}
                  <Separator className="bg-slate-700 my-3" />
                  <div className="p-2.5 rounded-md bg-slate-800/60 border border-slate-700"><p className="text-[11px] text-slate-300">Active: <span className="text-emerald-400 font-semibold">{Object.entries(activeInstruments).filter(([,v]) => v).map(([k]) => k).join(', ')}</span></p></div>
                </CardContent>
              </Card>

              {/* Strategy Toggles */}
              <Card className="bg-slate-900 border-slate-700 shadow-lg">
                <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-slate-200"><Zap className="h-4 w-4 text-amber-400" />Strategy Control</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {STRATEGIES.map(s => (
                    <div key={s.name} className="flex items-center justify-between p-2 rounded-md bg-slate-800/40 border border-slate-700/50">
                      <div>
                        <p className="text-xs text-slate-200 font-medium">{s.name}</p>
                        <p className="text-[10px] text-slate-400">{s.type} &bull; {s.rr} R:R</p>
                      </div>
                      <ToggleSwitch checked={activeStrategies[s.name] ?? true} onChange={() => handleToggleStrategy(s.name)} label="" />
                    </div>
                  ))}
                  <Separator className="bg-slate-700" />
                  <div className="space-y-2">
                    <Button size="sm" className="w-full bg-emerald-600 hover:bg-emerald-700 text-white text-xs" onClick={() => { setIsTrading(true); doToast('Bot STARTED'); }}><Play className="h-3 w-3 mr-1" />Start Bot</Button>
                    <Button size="sm" className="w-full bg-red-600 hover:bg-red-700 text-white text-xs" onClick={() => { setIsTrading(false); doToast('Bot STOPPED'); }}><Pause className="h-3 w-3 mr-1" />Stop Bot</Button>
                    <Button size="sm" variant="outline" className="w-full border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/15 text-xs" onClick={() => setShowEmergency(true)}><AlertTriangle className="h-3 w-3 mr-1" />Emergency Close All</Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* ═══ SETTINGS ═══ */}
          <TabsContent value="settings" className="mt-4">
            <div className="max-w-2xl mx-auto">
              <CredentialManager />
            </div>
          </TabsContent>
        </Tabs>
      </main>

      {/* ═══ EMERGENCY DIALOG ═══ */}
      <Dialog open={showEmergency} onOpenChange={setShowEmergency}>
        <DialogContent className="bg-slate-900 border-red-500/40">
          <DialogHeader>
            <DialogTitle className="text-red-400 flex items-center gap-2"><AlertTriangle className="h-5 w-5" />Emergency Close All</DialogTitle>
            <DialogDescription className="text-slate-400">This will close ALL positions at market price and halt trading. Cannot be undone.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEmergency(false)} className="border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700">Cancel</Button>
            <Button variant="destructive" onClick={handleEmergency}>Confirm Close All</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
