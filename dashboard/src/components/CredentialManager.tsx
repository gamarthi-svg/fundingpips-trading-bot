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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import { Shield, Key, Server, CheckCircle2, AlertTriangle, Trash2, Eye, EyeOff, Lock } from 'lucide-react';

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
  bootcamp?: boolean;
}

const REGIONS = [
  { value: 'new-york', label: 'New York (US)' },
  { value: 'london', label: 'London (EU)' },
  { value: 'singapore', label: 'Singapore (Asia)' },
];

const PHASES_2STEP = ['phase1', 'phase2', 'funded'];
const PHASES_3STEP = ['phase1', 'phase2', 'phase3', 'funded'];

export default function CredentialManager() {
  const [status, setStatus] = useState<CredentialStatus | null>(null);
  const [propFirms, setPropFirms] = useState<PropFirmInfo[]>([]);
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

    try {
      const r = await fetch(`${API_BASE}/api/prop-firms`);
      if (r.ok) {
        const data = await r.json();
        setPropFirms(data.firms || []);
      }
    } catch (e) {
      // Use defaults
      setPropFirms([
        { id: 'fundingpips', name: 'FundingPips', steps: 2, account_sizes: [10000, 50000, 100000, 200000], default_size: 10000, phases: ['phase1', 'phase2', 'funded'] },
        { id: 'the5ers', name: 'The5%ers', steps: 3, account_sizes: [5000], default_size: 5000, phases: ['phase1', 'phase2', 'phase3', 'funded'], bootcamp: true },
      ]);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const currentFirm = propFirms.find(f => f.id === propFirm);
  const accountSizes = currentFirm?.account_sizes || [10000, 50000, 100000, 200000];
  const phases = (currentFirm?.steps || 2) === 3 ? PHASES_3STEP : PHASES_2STEP;

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
        setToken(''); // Clear token from form
        fetchStatus();
      } else {
        toast.error(result.message || result.detail || 'Failed to save credentials');
      }
    } catch (err: any) {
      toast.error('Network error: ' + (err.message || 'Unknown'));
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
