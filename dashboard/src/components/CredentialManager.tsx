/**
 * Secure credential management component.
 *
 * The MetaAPI token is entered via a password input (never visible) and
 * sent to the backend over HTTPS. The backend encrypts it with AES-256-GCM
 * before storing. The token is NEVER returned in any API response.
 */

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import {
  Shield, Key, Server, CheckCircle2, AlertTriangle, Trash2, Eye, EyeOff, Lock,
  Trophy, Target, TrendingDown, Clock, Percent, Banknote, Star,
} from 'lucide-react';

const API_BASE = '';

interface CredentialStatus {
  configured: boolean;
  account_id: string | null;
  region: string | null;
  prop_firm: string | null;
  account_type: string | null;
  account_size: number | null;
  phase: string | null;
  the5ers_step: number | null;
  updated_at: number | null;
  error?: string;
}

interface PropFirmInfo {
  id: string;
  name: string;
  steps: number;
  account_sizes: number[];
  default_size: number;
  phases: string[];
  time_limit: string;
  profit_split: number;
  refund: boolean;
  features: string[];
  bootcamp?: boolean;
}

const DEFAULT_PROP_FIRMS: PropFirmInfo[] = [
  {
    id: 'fundingpips',
    name: 'FundingPips',
    steps: 2,
    account_sizes: [10000, 50000, 100000, 200000],
    default_size: 10000,
    phases: ['phase1', 'phase2', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.80,
    refund: true,
    features: ['No time limit', 'News trading allowed', 'EA allowed'],
  },
  {
    id: 'the5ers',
    name: 'The5%ers',
    steps: 3,
    account_sizes: [5000, 10000, 20000, 40000, 60000, 100000],
    default_size: 5000,
    phases: ['phase1', 'phase2', 'phase3', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.50,
    refund: false,
    bootcamp: true,
    features: ['3-step challenge', 'Scaling plan', 'Instant bootcamp'],
  },
  {
    id: 'ftmo',
    name: 'FTMO',
    steps: 2,
    account_sizes: [10000, 25000, 50000, 100000, 200000],
    default_size: 10000,
    phases: ['phase1', 'phase2', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.80,
    refund: true,
    features: ['No time limit', 'Swing account', 'Scaling plan'],
  },
  {
    id: 'trueforexfunds',
    name: 'True Forex Funds',
    steps: 2,
    account_sizes: [10000, 25000, 50000, 100000, 200000],
    default_size: 10000,
    phases: ['phase1', 'phase2', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.80,
    refund: true,
    features: ['Bi-weekly payouts', 'No time limit', 'EA allowed'],
  },
  {
    id: 'blueguardian',
    name: 'Blue Guardian',
    steps: 2,
    account_sizes: [10000, 25000, 50000, 100000, 200000],
    default_size: 10000,
    phases: ['phase1', 'phase2', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.85,
    refund: true,
    features: ['85% split', 'No time limit', 'News allowed'],
  },
  {
    id: 'surgetrader',
    name: 'SurgeTrader',
    steps: 1,
    account_sizes: [25000, 50000, 100000, 250000, 500000, 1000000],
    default_size: 25000,
    phases: ['phase1', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.75,
    refund: false,
    features: ['1-step evaluation', 'Up to $1M', 'No daily loss'],
  },
  {
    id: 'apex',
    name: 'Apex Trader Funding',
    steps: 1,
    account_sizes: [25000, 50000, 100000, 150000, 250000, 300000],
    default_size: 50000,
    phases: ['phase1', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 1.00,
    refund: false,
    features: ['100% 1st $25K', 'No daily DD', 'Futures only'],
  },
  {
    id: 'topstep',
    name: 'Topstep',
    steps: 1,
    account_sizes: [50000, 100000, 150000],
    default_size: 50000,
    phases: ['phase1', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.90,
    refund: true,
    features: ['Futures', '90% split', 'Express fund'],
  },
  {
    id: 'bulenox',
    name: 'Bulenox',
    steps: 1,
    account_sizes: [10000, 25000, 50000, 100000, 150000, 250000],
    default_size: 25000,
    phases: ['phase1', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.90,
    refund: false,
    features: ['Futures', '90% split', 'No daily DD'],
  },
  {
    id: 'fundednext',
    name: 'FundedNext',
    steps: 2,
    account_sizes: [6000, 15000, 25000, 50000, 100000, 200000],
    default_size: 15000,
    phases: ['phase1', 'phase2', 'funded'],
    time_limit: 'Unlimited',
    profit_split: 0.95,
    refund: true,
    features: ['95% split', 'No time limit', 'News allowed'],
  },
];

const REGIONS = [
  { value: 'new-york', label: 'New York (US)' },
  { value: 'london', label: 'London (EU)' },
  { value: 'singapore', label: 'Singapore (Asia)' },
];

const PHASES_2STEP = ['phase1', 'phase2', 'funded'];
const PHASES_3STEP = ['phase1', 'phase2', 'phase3', 'funded'];

// Phase rules for each prop firm
const PHASE_RULES: Record<string, Record<string, { profitTarget: string; maxDrawdown: string; dailyDrawdown: string; description: string }>> = {
  fundingpips: {
    phase1: { profitTarget: '8%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 1: Reach 8% profit target without hitting drawdown limits' },
    phase2: { profitTarget: '5%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 2: Reach 5% profit target to get funded' },
    funded: { profitTarget: 'No target', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Funded: Trade with real capital, keep 80% of profits' },
  },
  ftmo: {
    phase1: { profitTarget: '10%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 1: Reach 10% profit target' },
    phase2: { profitTarget: '5%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 2: Reach 5% profit target to get funded' },
    funded: { profitTarget: 'No target', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Funded: Trade with real capital, keep 80% of profits' },
  },
  the5ers: {
    phase1: { profitTarget: '6%', maxDrawdown: '6%', dailyDrawdown: 'N/A', description: 'Bootcamp Step 1: Reach 6% profit target' },
    phase2: { profitTarget: '5%', maxDrawdown: '6%', dailyDrawdown: 'N/A', description: 'Bootcamp Step 2: Reach 5% profit target' },
    phase3: { profitTarget: '5%', maxDrawdown: '6%', dailyDrawdown: 'N/A', description: 'Bootcamp Step 3: Reach 5% profit target' },
    funded: { profitTarget: 'No target', maxDrawdown: '6%', dailyDrawdown: 'N/A', description: 'Funded: Start with 50% profit split, scale up to 80%' },
  },
  trueforexfunds: {
    phase1: { profitTarget: '8%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 1: Reach 8% profit target' },
    phase2: { profitTarget: '5%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 2: Reach 5% profit target to get funded' },
    funded: { profitTarget: 'No target', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Funded: Bi-weekly payouts, keep 80% of profits' },
  },
  blueguardian: {
    phase1: { profitTarget: '8%', maxDrawdown: '10%', dailyDrawdown: '4%', description: 'Phase 1: Reach 8% profit target' },
    phase2: { profitTarget: '4%', maxDrawdown: '10%', dailyDrawdown: '4%', description: 'Phase 2: Reach 4% profit target to get funded' },
    funded: { profitTarget: 'No target', maxDrawdown: '10%', dailyDrawdown: '4%', description: 'Funded: Keep 85% of profits' },
  },
  surgetrader: {
    phase1: { profitTarget: '10%', maxDrawdown: '8%', dailyDrawdown: 'None', description: '1-Step: Reach 10% profit target, no daily drawdown' },
    funded: { profitTarget: 'No target', maxDrawdown: '8%', dailyDrawdown: 'None', description: 'Funded: Keep 75% of profits' },
  },
  apex: {
    phase1: { profitTarget: 'No target', maxDrawdown: 'Trailing', dailyDrawdown: 'None', description: 'Evaluation: Trade profitably without hitting trailing drawdown' },
    funded: { profitTarget: 'No target', maxDrawdown: 'Trailing', dailyDrawdown: 'None', description: 'Funded: Keep 100% of first $25K, then 90%' },
  },
  topstep: {
    phase1: { profitTarget: '$3K', maxDrawdown: '$2K', dailyDrawdown: 'None', description: 'Trading Combine: Reach profit target without max loss' },
    funded: { profitTarget: 'No target', maxDrawdown: 'Varies', dailyDrawdown: 'None', description: 'Funded: Keep first $5K, then 90%' },
  },
  bulenox: {
    phase1: { profitTarget: 'No target', maxDrawdown: 'Trailing', dailyDrawdown: 'None', description: 'Evaluation: Trade without hitting trailing drawdown' },
    funded: { profitTarget: 'No target', maxDrawdown: 'Trailing', dailyDrawdown: 'None', description: 'Funded: Keep 90% of profits' },
  },
  fundednext: {
    phase1: { profitTarget: '10%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 1: Reach 10% profit target' },
    phase2: { profitTarget: '5%', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Phase 2: Reach 5% profit target to get funded' },
    funded: { profitTarget: 'No target', maxDrawdown: '10%', dailyDrawdown: '5%', description: 'Funded: Keep up to 95% of profits' },
  },
};

function formatPhaseLabel(p: string): string {
  if (p === 'funded') return 'Funded';
  return p.replace('phase', 'Phase ');
}

function PhaseDetailCard({
  phaseKey,
  rules,
}: {
  phaseKey: string;
  rules: { profitTarget: string; maxDrawdown: string; dailyDrawdown: string; description: string };
}) {
  const isFunded = phaseKey === 'funded';
  return (
    <div className={`rounded-lg border p-3 space-y-2 ${isFunded ? 'border-emerald-700/50 bg-emerald-950/20' : 'border-zinc-800 bg-zinc-900/50'}`}>
      <div className="flex items-center gap-2">
        {isFunded ? (
          <Trophy className="h-3.5 w-3.5 text-emerald-400" />
        ) : (
          <Target className="h-3.5 w-3.5 text-sky-400" />
        )}
        <span className={`text-xs font-semibold ${isFunded ? 'text-emerald-400' : 'text-sky-400'}`}>
          {formatPhaseLabel(phaseKey)}
        </span>
      </div>
      <p className="text-[11px] text-zinc-400 leading-snug">{rules.description}</p>
      <div className="grid grid-cols-3 gap-1.5 pt-1">
        <div className="text-center rounded bg-zinc-950 p-1.5">
          <div className="text-[10px] text-zinc-500">Profit</div>
          <div className="text-[11px] text-emerald-400 font-mono">{rules.profitTarget}</div>
        </div>
        <div className="text-center rounded bg-zinc-950 p-1.5">
          <div className="text-[10px] text-zinc-500">Max DD</div>
          <div className="text-[11px] text-red-400 font-mono">{rules.maxDrawdown}</div>
        </div>
        <div className="text-center rounded bg-zinc-950 p-1.5">
          <div className="text-[10px] text-zinc-500">Daily DD</div>
          <div className="text-[11px] text-amber-400 font-mono">{rules.dailyDrawdown}</div>
        </div>
      </div>
    </div>
  );
}

export default function CredentialManager() {
  const [status, setStatus] = useState<CredentialStatus | null>(null);
  const [propFirms, setPropFirms] = useState<PropFirmInfo[]>(DEFAULT_PROP_FIRMS);
  const [loading, setLoading] = useState(false);

  // Form state
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [accountId, setAccountId] = useState('');
  const [region, setRegion] = useState('new-york');
  const [propFirm, setPropFirm] = useState('fundingpips');
  const [accountSize, setAccountSize] = useState(10000);
  const [phase, setPhase] = useState('phase1');
  const [the5ersStep, setThe5ersStep] = useState(1);

  // Fetch status on mount
  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/credentials/status`);
      if (r.ok) {
        const data = await r.json();
        setStatus(data);
        if (data.prop_firm) setPropFirm(data.prop_firm);
        if (data.account_size) setAccountSize(data.account_size);
        if (data.phase) setPhase(data.phase);
        if (data.the5ers_step) setThe5ersStep(data.the5ers_step);
      }
    } catch (e) {
      // Backend may not be running — silent fail
    }

    // API fetch as enhancement — merge with defaults
    try {
      const r = await fetch(`${API_BASE}/api/prop-firms`);
      if (r.ok) {
        const data = await r.json();
        const fetched = (data.firms || []) as PropFirmInfo[];
        if (fetched.length > 0) {
          // Merge fetched firms with defaults (fetched takes precedence)
          const merged = [...DEFAULT_PROP_FIRMS];
          fetched.forEach((f: PropFirmInfo) => {
            const idx = merged.findIndex(m => m.id === f.id);
            if (idx >= 0) {
              merged[idx] = { ...merged[idx], ...f };
            } else {
              merged.push(f);
            }
          });
          setPropFirms(merged);
        }
      }
    } catch (e) {
      // Already have defaults — no action needed
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const currentFirm = propFirms.find(f => f.id === propFirm);
  const accountSizes = currentFirm?.account_sizes || [10000, 50000, 100000, 200000];
  const phases = (currentFirm?.steps || 2) === 3 ? PHASES_3STEP : PHASES_2STEP;
  const phaseRules = PHASE_RULES[propFirm];

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim()) {
      toast.error('MetaAPI Token is required');
      return;
    }
    if (!accountId.trim()) {
      toast.error('Account ID is required');
      return;
    }

    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/api/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: token.trim(),
          account_id: accountId.trim(),
          region,
          prop_firm: propFirm,
          account_type: currentFirm?.bootcamp ? 'bootcamp' : 'pro',
          account_size: Number(accountSize),
          phase,
          the5ers_step: the5ersStep,
        }),
      });

      const result = await r.json();
      if (r.ok && result.success) {
        toast.success(result.message || 'Credentials saved securely');
        setToken('');
        fetchStatus();
      } else {
        toast.error(result.message || result.detail || 'Failed to save credentials');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown';
      toast.error('Network error: ' + msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete() {
    if (!confirm('Delete all stored credentials? This cannot be undone.')) return;
    try {
      const r = await fetch(`${API_BASE}/api/credentials`, { method: 'DELETE' });
      if (r.ok) {
        toast.success('Credentials deleted');
        setStatus(null);
      } else {
        toast.error('Failed to delete credentials');
      }
    } catch (e) {
      toast.error('Network error');
    }
  }

  return (
    <div className="space-y-6">
      {/* Status Card */}
      <Card className="border-zinc-800 bg-zinc-950">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white text-base font-medium">
            <Shield className="h-4 w-4 text-emerald-400" />
            Credential Status
          </CardTitle>
          <CardDescription className="text-zinc-500">
            MetaAPI credentials are encrypted at rest with AES-256-GCM
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status?.configured ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                <span className="text-sm text-emerald-400">Configured</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="text-zinc-500">Account ID</div>
                <div className="text-zinc-300 font-mono">{status.account_id}</div>
                <div className="text-zinc-500">Prop Firm</div>
                <div className="text-zinc-300 capitalize">{status.prop_firm}</div>
                <div className="text-zinc-500">Account Size</div>
                <div className="text-zinc-300">${(status.account_size || 0).toLocaleString()}</div>
                <div className="text-zinc-500">Phase</div>
                <div className="text-zinc-300 capitalize">{status.phase}</div>
                <div className="text-zinc-500">Region</div>
                <div className="text-zinc-300 capitalize">{status.region}</div>
                {status.the5ers_step && status.the5ers_step > 1 && (
                  <>
                    <div className="text-zinc-500">5%ers Step</div>
                    <div className="text-zinc-300">{status.the5ers_step}</div>
                  </>
                )}
              </div>
              <Button
                variant="destructive"
                size="sm"
                className="mt-2"
                onClick={handleDelete}
              >
                <Trash2 className="h-3 w-3 mr-1" />
                Delete Credentials
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-zinc-500">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              <span className="text-sm">No credentials configured</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Setup Form */}
      <Card className="border-zinc-800 bg-zinc-950">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white text-base font-medium">
            <Key className="h-4 w-4 text-sky-400" />
            {status?.configured ? 'Update Credentials' : 'Configure MetaAPI'}
          </CardTitle>
          <CardDescription className="text-zinc-500">
            Your token is encrypted before storage and never exposed in responses
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            {/* Prop Firm Selection */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-zinc-400 text-xs">Prop Firm</Label>
                <Select value={propFirm} onValueChange={setPropFirm}>
                  <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-700">
                    {propFirms.map(f => (
                      <SelectItem key={f.id} value={f.id} className="text-zinc-200">
                        {f.name} {f.bootcamp ? '(Bootcamp)' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-zinc-400 text-xs">Account Size</Label>
                <Select
                  value={String(accountSize)}
                  onValueChange={v => setAccountSize(Number(v))}
                >
                  <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-700">
                    {accountSizes.map(size => (
                      <SelectItem key={size} value={String(size)} className="text-zinc-200">
                        ${size.toLocaleString()}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Phase & Region */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-zinc-400 text-xs">Current Phase</Label>
                <Select value={phase} onValueChange={setPhase}>
                  <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-700">
                    {phases.map(p => (
                      <SelectItem key={p} value={p} className="text-zinc-200 capitalize">
                        {p === 'funded' ? 'Funded' : p.replace('phase', 'Phase ')}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label className="text-zinc-400 text-xs">MetaAPI Region</Label>
                <Select value={region} onValueChange={setRegion}>
                  <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-700">
                    {REGIONS.map(r => (
                      <SelectItem key={r.value} value={r.value} className="text-zinc-200">
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* The5%ers step (conditional) */}
            {currentFirm?.bootcamp && (
              <div className="space-y-1.5">
                <Label className="text-zinc-400 text-xs">Bootcamp Step (1-3)</Label>
                <Select
                  value={String(the5ersStep)}
                  onValueChange={v => setThe5ersStep(Number(v))}
                >
                  <SelectTrigger className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-700">
                    <SelectItem value="1" className="text-zinc-200">Step 1 — 6% target</SelectItem>
                    <SelectItem value="2" className="text-zinc-200">Step 2 — 5% target</SelectItem>
                    <SelectItem value="3" className="text-zinc-200">Step 3 — Funded</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            <Separator className="bg-zinc-800" />

            {/* Firm Info Summary */}
            {currentFirm && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className="border-zinc-700 text-zinc-300 text-[10px]">
                    <Percent className="h-2.5 w-2.5 mr-1" />
                    {Math.round(currentFirm.profit_split * 100)}% Split
                  </Badge>
                  <Badge variant="outline" className="border-zinc-700 text-zinc-300 text-[10px]">
                    <Clock className="h-2.5 w-2.5 mr-1" />
                    {currentFirm.time_limit}
                  </Badge>
                  {currentFirm.refund && (
                    <Badge variant="outline" className="border-emerald-700 text-emerald-400 text-[10px]">
                      <Banknote className="h-2.5 w-2.5 mr-1" />
                      Refundable
                    </Badge>
                  )}
                  <Badge variant="outline" className="border-zinc-700 text-zinc-300 text-[10px]">
                    {currentFirm.steps}-step
                  </Badge>
                </div>
                <div className="flex flex-wrap gap-1">
                  {currentFirm.features.map(f => (
                    <Badge key={f} variant="secondary" className="bg-zinc-900 text-zinc-400 text-[10px]">
                      <Star className="h-2.5 w-2.5 mr-1" />
                      {f}
                    </Badge>
                  ))}
                </div>

                {/* Phase Detail Cards */}
                {phaseRules && (
                  <div className="pt-2">
                    <Label className="text-zinc-400 text-xs mb-2 block flex items-center gap-1">
                      <TrendingDown className="h-3 w-3" />
                      Phase Rules for {currentFirm.name}
                    </Label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {phases.map(p => {
                        const rules = phaseRules[p];
                        if (!rules) return null;
                        return (
                          <PhaseDetailCard
                            key={p}
                            phaseKey={p}
                            rules={rules}
                          />
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            <Separator className="bg-zinc-800" />

            {/* Account ID */}
            <div className="space-y-1.5">
              <Label className="text-zinc-400 text-xs flex items-center gap-1">
                <Server className="h-3 w-3" />
                MetaAPI Account ID
              </Label>
              <Input
                value={accountId}
                onChange={e => setAccountId(e.target.value)}
                placeholder="db865e4a-4e83-48a6-93af-73372f595a0c"
                className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9 font-mono text-xs"
              />
            </div>

            {/* Token (password field) */}
            <div className="space-y-1.5">
              <Label className="text-zinc-400 text-xs flex items-center gap-1">
                <Lock className="h-3 w-3" />
                MetaAPI Token
                <span className="text-amber-500 text-[10px] ml-1">(never shown after saving)</span>
              </Label>
              <div className="relative">
                <Input
                  type={showToken ? 'text' : 'password'}
                  value={token}
                  onChange={e => setToken(e.target.value)}
                  placeholder="eyJhbGciOiJSUzUxMi..."
                  className="bg-zinc-900 border-zinc-700 text-zinc-200 h-9 font-mono text-xs pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowToken(!showToken)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                >
                  {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="text-zinc-600 text-[10px]">
                Get your token from{' '}
                <a href="https://app.metaapi.cloud/token" target="_blank" rel="noopener noreferrer" className="text-sky-400 hover:underline">
                  app.metaapi.cloud/token
                </a>
                . Must include <code className="text-amber-400">market-data-client-api</code> permission.
              </p>
            </div>

            <Button
              type="submit"
              disabled={loading || !token.trim() || !accountId.trim()}
              className="w-full bg-sky-600 hover:bg-sky-700 text-white h-9"
            >
              {loading ? 'Validating & Encrypting...' : status?.configured ? 'Update Credentials' : 'Save Credentials'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
