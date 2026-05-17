/**
 * StrategyControl.tsx — Strategy Management Panel
 *
 * Displays all trading strategies grouped by category (Indices, Crypto, Metals, Energies, Forex).
 * Each strategy can be enabled/disabled, backtested, optimized, or run through Monte Carlo.
 * Includes bulk actions for portfolio-level operations.
 */

import { useState, useMemo } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import {
  TrendingUp,
  Zap,
  Circle,
  DollarSign,
  Play,
  Settings,
  LineChart,
  Shuffle,
  Power,
  PowerOff,
  Filter,
  BarChart3,
  Activity,
  Layers,
  CheckCircle2,
  X,
  Calendar,
  Gauge,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────────────────

interface StrategyInfo {
  id: string;
  name: string;
  symbol: string;
  category: string; // 'indices' | 'crypto' | 'metals' | 'energies' | 'forex'
  type: string; // 'scalp' | 'day' | 'swing'
  enabled: boolean;
  status?: string; // 'active' | 'inactive' | 'backtesting'
}

type CategoryKey = 'indices' | 'crypto' | 'metals' | 'energies' | 'forex';
type StrategyType = 'scalp' | 'day' | 'swing';

// ─── Strategy Data ───────────────────────────────────────────────────────────

const ALL_STRATEGIES: StrategyInfo[] = [
  // Indices
  { id: 'nas100_orb', name: 'NAS100 Opening Range', symbol: 'NAS100', category: 'indices', type: 'day', enabled: false },
  { id: 'nas100_trend', name: 'NAS100 Trend Pullback', symbol: 'NAS100', category: 'indices', type: 'swing', enabled: false },
  { id: 'us30_orb', name: 'US30 Opening Range', symbol: 'US30', category: 'indices', type: 'day', enabled: false },
  // Crypto
  { id: 'btc_breakout', name: 'BTC Range Breakout', symbol: 'BTCUSD', category: 'crypto', type: 'day', enabled: false },
  { id: 'btc_trend', name: 'BTC Trend Follow', symbol: 'BTCUSD', category: 'crypto', type: 'swing', enabled: false },
  { id: 'eth_breakout', name: 'ETH Range Breakout', symbol: 'ETHUSD', category: 'crypto', type: 'day', enabled: false },
  { id: 'sol_breakout', name: 'SOL Range Breakout', symbol: 'SOLUSD', category: 'crypto', type: 'day', enabled: false },
  { id: 'doge_breakout', name: 'DOGE Range Breakout', symbol: 'DOGEUSD', category: 'crypto', type: 'day', enabled: false },
  { id: 'xrp_breakout', name: 'XRP Range Breakout', symbol: 'XRPUSD', category: 'crypto', type: 'day', enabled: false },
  { id: 'ltc_breakout', name: 'LTC Range Breakout', symbol: 'LTCUSD', category: 'crypto', type: 'day', enabled: false },
  // Metals
  { id: 'xau_asian', name: 'XAU Asian Breakout', symbol: 'XAUUSD', category: 'metals', type: 'day', enabled: true },
  { id: 'xau_ny', name: 'XAU NY Momentum', symbol: 'XAUUSD', category: 'metals', type: 'day', enabled: true },
  { id: 'xau_swing', name: 'XAU Swing Trend', symbol: 'XAUUSD', category: 'metals', type: 'swing', enabled: false },
  // Energies
  { id: 'xti_session', name: 'Oil US Session', symbol: 'XTIUSD', category: 'energies', type: 'day', enabled: false },
  // Forex
  { id: 'eurusd_london', name: 'EURUSD London', symbol: 'EURUSD', category: 'forex', type: 'day', enabled: true },
  { id: 'eurusd_ny', name: 'EURUSD NY', symbol: 'EURUSD', category: 'forex', type: 'day', enabled: false },
  { id: 'usdjpy_tokyo', name: 'USDJPY Tokyo', symbol: 'USDJPY', category: 'forex', type: 'day', enabled: false },
  { id: 'gbpjpy_london', name: 'GBPJPY London', symbol: 'GBPJPY', category: 'forex', type: 'day', enabled: false },
  { id: 'gbpusd_range', name: 'GBPUSD Range', symbol: 'GBPUSD', category: 'forex', type: 'scalp', enabled: false },
  { id: 'usdchf_trend', name: 'USDCHF Trend', symbol: 'USDCHF', category: 'forex', type: 'swing', enabled: false },
];

// ─── Category Config ─────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<
  CategoryKey,
  { label: string; icon: React.ElementType; color: string }
> = {
  indices: { label: 'Indices', icon: TrendingUp, color: 'text-violet-400' },
  crypto: { label: 'Crypto', icon: Zap, color: 'text-orange-400' },
  metals: { label: 'Metals', icon: Circle, color: 'text-yellow-400' },
  energies: { label: 'Energies', icon: Zap, color: 'text-red-400' },
  forex: { label: 'Forex', icon: DollarSign, color: 'text-emerald-400' },
};

const TYPE_COLORS: Record<StrategyType, string> = {
  scalp: 'bg-amber-600/20 text-amber-400 border-amber-600/30',
  day: 'bg-sky-600/20 text-sky-400 border-sky-600/30',
  swing: 'bg-emerald-600/20 text-emerald-400 border-emerald-600/30',
};

const CATEGORIES: CategoryKey[] = ['indices', 'crypto', 'metals', 'energies', 'forex'];

// ─── Component ───────────────────────────────────────────────────────────────

export default function StrategyControl() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>(ALL_STRATEGIES);
  const [hiddenCategories, setHiddenCategories] = useState<Set<string>>(new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogType, setDialogType] = useState<'backtest' | 'optimize' | 'mc' | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyInfo | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsStrategy, setSettingsStrategy] = useState<StrategyInfo | null>(null);

  // Backtest form state
  const [btStartDate, setBtStartDate] = useState('');
  const [btEndDate, setBtEndDate] = useState('');
  const [btTimeframe, setBtTimeframe] = useState('H1');

  // Stats
  const enabledCount = useMemo(
    () => strategies.filter(s => s.enabled).length,
    [strategies]
  );
  const totalCount = strategies.length;

  const grouped = useMemo(() => {
    const map = new Map<CategoryKey, StrategyInfo[]>();
    CATEGORIES.forEach(cat => {
      const items = strategies.filter(s => s.category === cat);
      if (items.length > 0) map.set(cat, items);
    });
    return map;
  }, [strategies]);

  // ─── Actions ───────────────────────────────────────────────────────────

  function toggleStrategy(id: string) {
    setStrategies(prev =>
      prev.map(s => (s.id === id ? { ...s, enabled: !s.enabled } : s))
    );
  }

  function toggleCategory(cat: CategoryKey) {
    setStrategies(prev =>
      prev.map(s =>
        s.category === cat ? { ...s, enabled: !s.enabled } : s
      )
    );
  }

  function enableAll() {
    setStrategies(prev => prev.map(s => ({ ...s, enabled: true })));
    toast.success('All strategies enabled');
  }

  function disableAll() {
    setStrategies(prev => prev.map(s => ({ ...s, enabled: false })));
    toast.success('All strategies disabled');
  }

  function openDialog(strategy: StrategyInfo, type: 'backtest' | 'optimize' | 'mc') {
    setSelectedStrategy(strategy);
    setDialogType(type);
    // Set default dates
    const now = new Date();
    const threeMonthsAgo = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
    setBtEndDate(now.toISOString().split('T')[0]);
    setBtStartDate(threeMonthsAgo.toISOString().split('T')[0]);
    setDialogOpen(true);
  }

  function openSettings(strategy: StrategyInfo) {
    setSettingsStrategy(strategy);
    setSettingsOpen(true);
  }

  function runBacktest() {
    if (!selectedStrategy) return;
    toast.success(
      `Queued ${dialogType === 'backtest' ? 'backtest' : dialogType === 'optimize' ? 'optimization' : 'Monte Carlo'} for ${selectedStrategy.name}`,
      { description: `${btStartDate} to ${btEndDate} on ${btTimeframe}` }
    );
    setDialogOpen(false);
  }

  function runBulkBacktest() {
    const enabled = strategies.filter(s => s.enabled);
    if (enabled.length === 0) {
      toast.error('No strategies enabled');
      return;
    }
    toast.success(`Queued backtest for ${enabled.length} strategies`);
  }

  function runBulkMC() {
    const enabled = strategies.filter(s => s.enabled);
    if (enabled.length === 0) {
      toast.error('No strategies enabled');
      return;
    }
    toast.success(`Queued Monte Carlo for portfolio of ${enabled.length} strategies`);
  }

  function toggleCategoryVisibility(cat: CategoryKey) {
    setHiddenCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  }

  // ─── Render helpers ────────────────────────────────────────────────────

  function renderStrategyRow(strategy: StrategyInfo) {
    const typeColor = TYPE_COLORS[strategy.type as StrategyType] || TYPE_COLORS.day;
    const isActive = strategy.enabled;

    return (
      <div
        key={strategy.id}
        className={`grid grid-cols-[1fr_80px_70px_90px_160px] items-center gap-2 px-3 py-2 border-b border-zinc-800/50 last:border-0 transition-colors ${
          isActive ? 'bg-emerald-950/10' : 'hover:bg-zinc-900/30'
        }`}
      >
        {/* Strategy name */}
        <div className="flex items-center gap-2 min-w-0">
          <Switch
            checked={strategy.enabled}
            onCheckedChange={() => toggleStrategy(strategy.id)}
            className="data-[state=checked]:bg-emerald-600"
          />
          <div className="min-w-0">
            <div className="text-sm text-zinc-200 font-medium truncate">{strategy.name}</div>
            <div className="text-[10px] text-zinc-500 font-mono">{strategy.symbol}</div>
          </div>
        </div>

        {/* Symbol */}
        <div className="text-xs text-zinc-400 font-mono">{strategy.symbol}</div>

        {/* Type badge */}
        <div>
          <Badge variant="outline" className={`text-[10px] ${typeColor}`}>
            {strategy.type}
          </Badge>
        </div>

        {/* Status */}
        <div className="flex items-center gap-1.5">
          <div
            className={`h-1.5 w-1.5 rounded-full ${
              isActive ? 'bg-emerald-400' : 'bg-zinc-600'
            }`}
          />
          <span className="text-xs text-zinc-400">
            {isActive ? 'Active' : 'Inactive'}
          </span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-zinc-500 hover:text-sky-400 hover:bg-sky-950/30"
            onClick={() => openDialog(strategy, 'backtest')}
            title="Backtest"
          >
            <Play className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-zinc-500 hover:text-violet-400 hover:bg-violet-950/30"
            onClick={() => openDialog(strategy, 'optimize')}
            title="Optimize"
          >
            <BarChart3 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-zinc-500 hover:text-amber-400 hover:bg-amber-950/30"
            onClick={() => openDialog(strategy, 'mc')}
            title="Monte Carlo"
          >
            <Shuffle className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800"
            onClick={() => openSettings(strategy)}
            title="Settings"
          >
            <Settings className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    );
  }

  // ─── Main Render ───────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header with stats */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Layers className="h-5 w-5 text-sky-400" />
          <div>
            <h2 className="text-lg font-semibold text-white">Strategy Control</h2>
            <p className="text-xs text-zinc-500">
              {enabledCount} of {totalCount} strategies active
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className="border-emerald-700 text-emerald-400 text-[10px]">
            <Activity className="h-2.5 w-2.5 mr-1" />
            {enabledCount} Active
          </Badge>
          <Badge variant="outline" className="border-zinc-700 text-zinc-400 text-[10px]">
            {totalCount - enabledCount} Inactive
          </Badge>
        </div>
      </div>

      {/* Bulk Actions Toolbar */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950 p-2">
        <div className="flex items-center gap-1.5 px-2">
          <Filter className="h-3.5 w-3.5 text-zinc-500" />
          <span className="text-xs text-zinc-500 font-medium">Bulk:</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs border-zinc-700 bg-zinc-900 text-emerald-400 hover:bg-emerald-950/30 hover:border-emerald-700"
          onClick={enableAll}
        >
          <Power className="h-3 w-3 mr-1" />
          Enable All
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs border-zinc-700 bg-zinc-900 text-red-400 hover:bg-red-950/30 hover:border-red-700"
          onClick={disableAll}
        >
          <PowerOff className="h-3 w-3 mr-1" />
          Disable All
        </Button>
        <div className="w-px h-5 bg-zinc-800 mx-1" />
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs border-zinc-700 bg-zinc-900 text-sky-400 hover:bg-sky-950/30 hover:border-sky-700"
          onClick={runBulkBacktest}
        >
          <LineChart className="h-3 w-3 mr-1" />
          Backtest All
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs border-zinc-700 bg-zinc-900 text-amber-400 hover:bg-amber-950/30 hover:border-amber-700"
          onClick={runBulkMC}
        >
          <Shuffle className="h-3 w-3 mr-1" />
          MC All
        </Button>
      </div>

      {/* Category Filter Pills */}
      <div className="flex flex-wrap items-center gap-2">
        {CATEGORIES.map(cat => {
          const config = CATEGORY_CONFIG[cat];
          const Icon = config.icon;
          const isHidden = hiddenCategories.has(cat);
          return (
            <button
              key={cat}
              onClick={() => toggleCategoryVisibility(cat)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all ${
                isHidden
                  ? 'border-zinc-800 bg-zinc-900/50 text-zinc-600'
                  : 'border-zinc-700 bg-zinc-900 text-zinc-200 hover:border-zinc-600'
              }`}
            >
              <Icon className={`h-3 w-3 ${isHidden ? 'text-zinc-600' : config.color}`} />
              {config.label}
              {isHidden && <X className="h-2.5 w-2.5 text-zinc-600 ml-0.5" />}
            </button>
          );
        })}
      </div>

      {/* Strategy Tables by Category */}
      <div className="space-y-3">
        {Array.from(grouped.entries()).map(([cat, items]) => {
          if (hiddenCategories.has(cat)) return null;
          const config = CATEGORY_CONFIG[cat];
          const Icon = config.icon;
          const catEnabledCount = items.filter(s => s.enabled).length;

          return (
            <Card key={cat} className="border-zinc-800 bg-zinc-950 overflow-hidden">
              {/* Category header */}
              <div
                className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 bg-zinc-900/30 cursor-pointer hover:bg-zinc-900/50 transition-colors"
                onClick={() => toggleCategory(cat)}
                title="Click to toggle all strategies in this category"
              >
                <div className="flex items-center gap-2">
                  <Icon className={`h-4 w-4 ${config.color}`} />
                  <span className="text-sm font-semibold text-zinc-200">{config.label}</span>
                  <Badge variant="outline" className="border-zinc-700 text-zinc-500 text-[10px]">
                    {items.length}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  {catEnabledCount > 0 && (
                    <Badge variant="outline" className="border-emerald-700 text-emerald-400 text-[10px]">
                      {catEnabledCount} on
                    </Badge>
                  )}
                  <Switch
                    checked={catEnabledCount === items.length && items.length > 0}
                    className="data-[state=checked]:bg-emerald-600 scale-75"
                    onClick={e => e.stopPropagation()}
                    onCheckedChange={() => toggleCategory(cat)}
                  />
                </div>
              </div>

              {/* Table header */}
              <div className="grid grid-cols-[1fr_80px_70px_90px_160px] items-center gap-2 px-3 py-1.5 border-b border-zinc-800 bg-zinc-900/20">
                <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
                  Strategy
                </div>
                <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
                  Symbol
                </div>
                <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
                  Type
                </div>
                <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">
                  Status
                </div>
                <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider text-right">
                  Actions
                </div>
              </div>

              {/* Strategy rows */}
              <div>{items.map(renderStrategyRow)}</div>
            </Card>
          );
        })}
      </div>

      {/* ─── Backtest / Optimize / MC Dialog ───────────────────────── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-zinc-950 border-zinc-800 text-zinc-200 max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              {dialogType === 'backtest' && <Play className="h-4 w-4 text-sky-400" />}
              {dialogType === 'optimize' && <BarChart3 className="h-4 w-4 text-violet-400" />}
              {dialogType === 'mc' && <Shuffle className="h-4 w-4 text-amber-400" />}
              {dialogType === 'backtest' && 'Backtest'}
              {dialogType === 'optimize' && 'Optimize'}
              {dialogType === 'mc' && 'Monte Carlo'} — {selectedStrategy?.name}
            </DialogTitle>
            <DialogDescription className="text-zinc-500">
              {dialogType === 'backtest' && 'Run a historical backtest for this strategy'}
              {dialogType === 'optimize' && 'Run walk-forward optimization'}
              {dialogType === 'mc' && 'Run Monte Carlo simulation for robustness'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            {/* Date range */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-zinc-400 text-xs flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  Start Date
                </Label>
                <Input
                  type="date"
                  value={btStartDate}
                  onChange={e => setBtStartDate(e.target.value)}
                  className="bg-zinc-900 border-zinc-700 text-zinc-200 h-8 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-zinc-400 text-xs flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  End Date
                </Label>
                <Input
                  type="date"
                  value={btEndDate}
                  onChange={e => setBtEndDate(e.target.value)}
                  className="bg-zinc-900 border-zinc-700 text-zinc-200 h-8 text-xs"
                />
              </div>
            </div>

            {/* Timeframe */}
            <div className="space-y-1">
              <Label className="text-zinc-400 text-xs flex items-center gap-1">
                <Gauge className="h-3 w-3" />
                Timeframe
              </Label>
              <Select value={btTimeframe} onValueChange={setBtTimeframe}>
                <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-700">
                  <SelectItem value="M5" className="text-zinc-200 text-xs">M5</SelectItem>
                  <SelectItem value="M15" className="text-zinc-200 text-xs">M15</SelectItem>
                  <SelectItem value="M30" className="text-zinc-200 text-xs">M30</SelectItem>
                  <SelectItem value="H1" className="text-zinc-200 text-xs">H1</SelectItem>
                  <SelectItem value="H4" className="text-zinc-200 text-xs">H4</SelectItem>
                  <SelectItem value="D1" className="text-zinc-200 text-xs">D1</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* MC-specific options */}
            {dialogType === 'mc' && (
              <div className="rounded-lg border border-amber-800/30 bg-amber-950/20 p-3 space-y-2">
                <div className="text-xs font-medium text-amber-400">Monte Carlo Settings</div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-zinc-500 text-[10px]">Iterations</Label>
                    <Input
                      defaultValue="1000"
                      className="bg-zinc-900 border-zinc-700 text-zinc-200 h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-zinc-500 text-[10px]">Confidence</Label>
                    <Input
                      defaultValue="95%"
                      className="bg-zinc-900 border-zinc-700 text-zinc-200 h-7 text-xs"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Optimization-specific options */}
            {dialogType === 'optimize' && (
              <div className="rounded-lg border border-violet-800/30 bg-violet-950/20 p-3 space-y-2">
                <div className="text-xs font-medium text-violet-400">Walk-Forward Settings</div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-zinc-500 text-[10px]">In-Sample %</Label>
                    <Input
                      defaultValue="70"
                      className="bg-zinc-900 border-zinc-700 text-zinc-200 h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-zinc-500 text-[10px]">Out-of-Sample %</Label>
                    <Input
                      defaultValue="30"
                      className="bg-zinc-900 border-zinc-700 text-zinc-200 h-7 text-xs"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              className="border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
              onClick={() => setDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className={`text-white ${
                dialogType === 'backtest'
                  ? 'bg-sky-600 hover:bg-sky-700'
                  : dialogType === 'optimize'
                  ? 'bg-violet-600 hover:bg-violet-700'
                  : 'bg-amber-600 hover:bg-amber-700'
              }`}
              onClick={runBacktest}
            >
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              Queue {dialogType === 'backtest' ? 'Backtest' : dialogType === 'optimize' ? 'Optimization' : 'MC'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Settings Dialog ────────────────────────────────────────── */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="bg-zinc-950 border-zinc-800 text-zinc-200 max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Settings className="h-4 w-4 text-zinc-400" />
              {settingsStrategy?.name}
            </DialogTitle>
            <DialogDescription className="text-zinc-500">
              Configure parameters for {settingsStrategy?.symbol}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-zinc-400 text-xs">Strategy ID</Label>
                <Input
                  value={settingsStrategy?.id || ''}
                  readOnly
                  className="bg-zinc-900 border-zinc-700 text-zinc-500 h-8 text-xs font-mono"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-zinc-400 text-xs">Symbol</Label>
                <Input
                  value={settingsStrategy?.symbol || ''}
                  readOnly
                  className="bg-zinc-900 border-zinc-700 text-zinc-500 h-8 text-xs font-mono"
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-zinc-400 text-xs">Risk Per Trade (%)</Label>
              <Input
                type="number"
                defaultValue={1.0}
                step={0.1}
                min={0.1}
                max={5}
                className="bg-zinc-900 border-zinc-700 text-zinc-200 h-8 text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-zinc-400 text-xs">Max Daily Loss (%)</Label>
              <Input
                type="number"
                defaultValue={3}
                step={0.5}
                min={0.5}
                max={10}
                className="bg-zinc-900 border-zinc-700 text-zinc-200 h-8 text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-zinc-400 text-xs">Position Sizing</Label>
              <Select defaultValue="fixed_fractional">
                <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-700">
                  <SelectItem value="fixed" className="text-zinc-200 text-xs">Fixed Lot</SelectItem>
                  <SelectItem value="fixed_fractional" className="text-zinc-200 text-xs">Fixed Fractional</SelectItem>
                  <SelectItem value="kelly" className="text-zinc-200 text-xs">Kelly Criterion</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              className="border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
              onClick={() => setSettingsOpen(false)}
            >
              Close
            </Button>
            <Button
              size="sm"
              className="bg-sky-600 hover:bg-sky-700 text-white"
              onClick={() => {
                toast.success(`Saved settings for ${settingsStrategy?.name}`);
                setSettingsOpen(false);
              }}
            >
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
