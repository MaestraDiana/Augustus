import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { formatDate } from '../utils/time';
import UsageChart from '../components/charts/UsageChart';
import { AGENT_COLORS } from '../utils/constants';

/** Format a token count to a human-readable string (e.g. 142500 → "142.5K"). */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

interface AgentUsage {
  agent_id: string;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost: number;
  session_count: number;
  agent_status?: string; // 'active' | 'idle' | 'paused' | 'deleted' | 'error'
}

interface UsageData {
  daySummary: any;
  monthSummary: any;
  allSummary: any;
  dailyData: any[];
  settings: any;
}

export default function Usage() {
  const [period, setPeriod] = useState('30d');
  const [dailyData, setDailyData] = useState<any[]>([]);

  const { data, loading } = useApi<UsageData>(
    async () => {
      const [daySummary, monthSummary, allSummary, dailyRes, settings] = await Promise.all([
        api.usage.summary(),
        api.usage.summary('month'),
        api.usage.summary('all'),
        api.usage.daily(30),
        api.settings.get(),
      ]);
      return { daySummary, monthSummary, allSummary, dailyData: dailyRes, settings };
    },
    [],
  );

  const daySummary = data?.daySummary ?? null;
  const monthSummary = data?.monthSummary ?? null;
  const allSummary = data?.allSummary ?? null;
  const settings = data?.settings ?? null;

  // Sync initial daily data from useApi result
  useEffect(() => {
    if (data?.dailyData) setDailyData(data.dailyData);
  }, [data]);

  // Re-fetch chart data when period changes
  useEffect(() => {
    if (loading) return;
    const days = period === '7d' ? 7 : period === '90d' ? 90 : 30;
    api.usage.daily(days).then(setDailyData).catch(console.error);
  }, [period]);

  // Derive budget card values from API data
  const dailySpend = daySummary?.total_cost ?? 0;
  const dailyCeiling = settings?.budget_per_day ?? 25;
  const monthlySpend = monthSummary?.total_cost ?? 0;
  const monthlySessions = monthSummary?.session_count ?? 0;
  const monthlyTokensIn = monthSummary?.total_tokens_in ?? 0;
  const monthlyTokensOut = monthSummary?.total_tokens_out ?? 0;
  const totalSpend = allSummary?.total_cost ?? 0;
  const warningThreshold = settings?.budget_warning ?? 50;
  const hardStop = settings?.budget_hard_stop ?? 100;
  const totalSessions = allSummary?.session_count ?? 0;
  const perSessionAverage = totalSessions > 0 ? totalSpend / totalSessions : 0;
  const perSessionCeiling = settings?.budget_per_session ?? 5;
  const estimatedRemaining = perSessionAverage > 0
    ? Math.floor((hardStop - totalSpend) / perSessionAverage)
    : 0;

  // By-agent breakdown (from all-time summary)
  const byAgent: AgentUsage[] = allSummary?.by_agent ?? [];

  // Chart data: transform daily API response to chart format
  const chartData = dailyData.map((d: any) => ({
    date: formatDate(d.date),
    total: d.cost ?? 0,
  }));

  // Compute footer totals from day summary
  const footerSessions = daySummary?.session_count ?? 0;
  const footerTokensIn = daySummary?.total_tokens_in ?? 0;
  const footerTokensOut = daySummary?.total_tokens_out ?? 0;
  const footerCost = daySummary?.total_cost ?? 0;

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Loading usage data...
      </div>
    );
  }

  const dailyPercentage = dailyCeiling > 0 ? (dailySpend / dailyCeiling) * 100 : 0;
  const totalPercentage = hardStop > 0 ? (totalSpend / hardStop) * 100 : 0;
  const perSessionPercentage = perSessionCeiling > 0 ? (perSessionAverage / perSessionCeiling) * 100 : 0;
  const warningMarkerPct = hardStop > 0 ? (warningThreshold / hardStop) * 100 : 66.67;

  const getDailyFillColor = () => {
    if (dailyPercentage >= 90) return 'red';
    if (dailyPercentage >= 70) return 'amber';
    return 'green';
  };

  return (
    <div>
      {/* Alerts */}
      {dailyPercentage >= 70 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
          padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-md)',
          marginBottom: 'var(--space-5)', background: 'var(--accent-attention-dim)',
          border: '1px solid var(--accent-attention)', color: 'var(--accent-attention)'
        }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <span style={{ fontSize: '14px', fontWeight: 500 }}>
            Warning threshold breached: Daily spend at {dailyPercentage.toFixed(0)}% of ceiling (${dailySpend.toFixed(2)} / ${dailyCeiling.toFixed(2)})
          </span>
          <button style={{
            marginLeft: 'auto', padding: 'var(--space-1) var(--space-2)',
            background: 'transparent', border: '1px solid currentColor', borderRadius: 'var(--radius-sm)',
            color: 'inherit', fontSize: '12px', cursor: 'pointer', opacity: 0.7
          }}>
            Dismiss
          </button>
        </div>
      )}

      {/* Budget Overview Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        {/* Daily Spend */}
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontWeight: 500 }}>Daily Spend</span>
            <div style={{
              width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 'var(--radius-md)', background: 'var(--bg-raised)', color: 'var(--text-muted)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 6v6l4 2" />
              </svg>
            </div>
          </div>
          <div style={{
            fontFamily: 'var(--font-data)', fontSize: '28px', fontWeight: 500,
            color: dailyPercentage >= 90 ? 'var(--accent-alert)' : dailyPercentage >= 70 ? 'var(--accent-attention)' : 'var(--text-primary)',
            marginBottom: 'var(--space-2)'
          }}>
            ${dailySpend.toFixed(2)}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            of <strong style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>${dailyCeiling.toFixed(2)}</strong> daily ceiling
          </div>
          <div style={{ marginTop: 'var(--space-3)' }}>
            <div style={{ height: '8px', background: 'var(--border-color)', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: '4px', width: `${Math.min(dailyPercentage, 100)}%`,
                background: getDailyFillColor() === 'red' ? 'var(--accent-alert)' :
                  getDailyFillColor() === 'amber' ? 'var(--accent-attention)' : 'var(--accent-success)',
                transition: 'width var(--transition-transform)'
              }}></div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--space-1)', fontSize: '11px', color: 'var(--text-muted)' }}>
              <span>$0</span>
              <span>${dailyCeiling.toFixed(0)}</span>
            </div>
          </div>
        </div>

        {/* Monthly Spend */}
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontWeight: 500 }}>Monthly Spend</span>
            <div style={{
              width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 'var(--radius-md)', background: 'var(--bg-raised)', color: 'var(--text-muted)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
            </div>
          </div>
          <div style={{ fontFamily: 'var(--font-data)', fontSize: '28px', fontWeight: 500, color: 'var(--text-primary)', marginBottom: 'var(--space-2)' }}>
            ${monthlySpend.toFixed(2)}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            <strong style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>{monthlySessions}</strong> sessions · All-time: <strong style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>${totalSpend.toFixed(2)}</strong>
          </div>
          <div style={{ marginTop: 'var(--space-3)', position: 'relative' }}>
            <div style={{ height: '8px', background: 'var(--border-color)', borderRadius: '4px', overflow: 'visible', position: 'relative' }}>
              <div style={{
                height: '100%', borderRadius: '4px', width: `${Math.min(totalPercentage, 100)}%`,
                background: 'var(--accent-success)', transition: 'width var(--transition-transform)'
              }}></div>
              <div style={{
                position: 'absolute', top: '-2px', left: `${Math.min(warningMarkerPct, 100)}%`,
                width: '2px', height: '12px', background: 'var(--accent-attention)', borderRadius: '1px'
              }}></div>
              <div style={{
                position: 'absolute', top: '-2px', left: '100%',
                width: '2px', height: '12px', background: 'var(--accent-alert)', borderRadius: '1px'
              }}></div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--space-1)', fontSize: '11px', color: 'var(--text-muted)' }}>
              <span>$0</span>
              <span>${hardStop.toFixed(0)}</span>
            </div>
          </div>
        </div>

        {/* Per-Session Average */}
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontWeight: 500 }}>Per-Session Average</span>
            <div style={{
              width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 'var(--radius-md)', background: 'var(--bg-raised)', color: 'var(--text-muted)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
          </div>
          <div style={{
            fontFamily: 'var(--font-data)', fontSize: '28px', fontWeight: 500,
            color: perSessionPercentage > 100 ? 'var(--accent-attention)' : 'var(--accent-success)',
            marginBottom: 'var(--space-2)'
          }}>
            ${perSessionAverage.toFixed(2)}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Ceiling: <strong style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>${perSessionCeiling.toFixed(2)}</strong> per session
          </div>
          <div style={{ marginTop: 'var(--space-3)' }}>
            <div style={{ height: '8px', background: 'var(--border-color)', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: '4px', width: `${Math.min(perSessionPercentage, 100)}%`,
                background: perSessionPercentage > 100 ? 'var(--accent-attention)' : 'var(--accent-success)',
                transition: 'width var(--transition-transform)'
              }}></div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--space-1)', fontSize: '11px', color: 'var(--text-muted)' }}>
              <span>$0</span>
              <span>${perSessionCeiling.toFixed(0)}</span>
            </div>
          </div>
        </div>

        {/* Estimated Remaining */}
        <div style={{
          background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontWeight: 500 }}>Estimated Remaining</span>
            <div style={{
              width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 'var(--radius-md)', background: 'var(--bg-raised)', color: 'var(--text-muted)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
            </div>
          </div>
          <div style={{ fontFamily: 'var(--font-data)', fontSize: '28px', fontWeight: 500, color: 'var(--text-primary)', marginBottom: 'var(--space-2)' }}>
            {estimatedRemaining > 0 ? `~${estimatedRemaining}` : '—'}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            {estimatedRemaining > 0 ? 'sessions at current rate' : 'No session data yet'}
          </div>
        </div>
      </div>

      {/* Usage Chart */}
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
        borderRadius: 'var(--radius-lg)', padding: 'var(--space-5)', marginBottom: 'var(--space-6)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-5)' }}>
          <h2 style={{ fontFamily: 'var(--font-voice)', fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)' }}>
            Daily Usage (Last {period === '7d' ? '7' : period === '90d' ? '90' : '30'} Days)
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <div style={{ display: 'flex', background: 'var(--bg-raised)', borderRadius: 'var(--radius-md)', padding: '2px' }}>
              <button
                onClick={() => setPeriod('7d')}
                style={{
                  padding: 'var(--space-2) var(--space-3)', background: period === '7d' ? 'var(--bg-surface)' : 'transparent',
                  border: 'none', fontSize: '13px', color: period === '7d' ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer', borderRadius: 'var(--radius-sm)', boxShadow: period === '7d' ? 'var(--shadow-card)' : 'none'
                }}
              >7D</button>
              <button
                onClick={() => setPeriod('30d')}
                style={{
                  padding: 'var(--space-2) var(--space-3)', background: period === '30d' ? 'var(--bg-surface)' : 'transparent',
                  border: 'none', fontSize: '13px', color: period === '30d' ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer', borderRadius: 'var(--radius-sm)', boxShadow: period === '30d' ? 'var(--shadow-card)' : 'none'
                }}
              >30D</button>
              <button
                onClick={() => setPeriod('90d')}
                style={{
                  padding: 'var(--space-2) var(--space-3)', background: period === '90d' ? 'var(--bg-surface)' : 'transparent',
                  border: 'none', fontSize: '13px', color: period === '90d' ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer', borderRadius: 'var(--radius-sm)', boxShadow: period === '90d' ? 'var(--shadow-card)' : 'none'
                }}
              >90D</button>
            </div>
            <button className="btn btn-secondary btn-sm">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Export PNG
            </button>
          </div>
        </div>

        <div style={{ height: '300px' }}>
          {chartData.length > 0 ? (
            <UsageChart data={chartData} dailyCeiling={dailyCeiling} warningThreshold={warningThreshold} />
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', fontSize: '14px' }}>
              No usage data yet. Run some sessions to see daily cost trends.
            </div>
          )}
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-5)',
          marginTop: 'var(--space-4)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--border-color)'
        }}>
          {byAgent.map((agent, i) => {
            const isDeleted = agent.agent_status === 'deleted';
            return (
              <div key={agent.agent_id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '13px', color: 'var(--text-secondary)', opacity: isDeleted ? 0.5 : 1 }}>
                <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: AGENT_COLORS[i % AGENT_COLORS.length] }}></span>
                {agent.agent_id}{isDeleted ? ' (Deleted)' : ''}
              </div>
            );
          })}
          {byAgent.length === 0 && (
            <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>No agents</div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '13px', color: 'var(--text-secondary)' }}>
            <div style={{
              width: '20px', height: '2px',
              background: 'repeating-linear-gradient(to right, var(--accent-attention) 0, var(--accent-attention) 4px, transparent 4px, transparent 8px)'
            }}></div>
            Daily Ceiling
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '13px', color: 'var(--text-secondary)' }}>
            <div style={{
              width: '20px', height: '2px',
              background: 'repeating-linear-gradient(to right, var(--accent-alert) 0, var(--accent-alert) 2px, transparent 2px, transparent 6px)'
            }}></div>
            Warning Threshold
          </div>
        </div>
      </div>

      {/* Agent Breakdown Table */}
      <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: 'var(--space-4) var(--space-5)', borderBottom: '1px solid var(--border-color)'
        }}>
          <h2 style={{ fontFamily: 'var(--font-voice)', fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)' }}>
            Per-Agent Breakdown
          </h2>
          <button className="btn btn-secondary btn-sm">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export CSV
          </button>
        </div>

        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-raised)' }}>
              <th style={{
                padding: 'var(--space-3) var(--space-4)', textAlign: 'left', fontSize: '12px',
                fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
                letterSpacing: '0.5px', borderBottom: '1px solid var(--border-color)'
              }}>Agent</th>
              <th style={{
                padding: 'var(--space-3) var(--space-4)', textAlign: 'left', fontSize: '12px',
                fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
                letterSpacing: '0.5px', borderBottom: '1px solid var(--border-color)'
              }}>Sessions</th>
              <th style={{
                padding: 'var(--space-3) var(--space-4)', textAlign: 'left', fontSize: '12px',
                fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
                letterSpacing: '0.5px', borderBottom: '1px solid var(--border-color)'
              }}>Tokens In</th>
              <th style={{
                padding: 'var(--space-3) var(--space-4)', textAlign: 'left', fontSize: '12px',
                fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
                letterSpacing: '0.5px', borderBottom: '1px solid var(--border-color)'
              }}>Tokens Out</th>
              <th style={{
                padding: 'var(--space-3) var(--space-4)', textAlign: 'left', fontSize: '12px',
                fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
                letterSpacing: '0.5px', borderBottom: '1px solid var(--border-color)'
              }}>Total Cost</th>
            </tr>
          </thead>
          <tbody>
            {byAgent.length === 0 && (
              <tr>
                <td colSpan={5} style={{
                  padding: 'var(--space-6)', textAlign: 'center',
                  fontSize: '14px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)'
                }}>
                  No usage data yet. Run some sessions to see per-agent cost breakdown.
                </td>
              </tr>
            )}
            {byAgent.map((agent, i) => {
              const isDeleted = agent.agent_status === 'deleted';
              const rowOpacity = isDeleted ? 0.5 : 1;

              return (
                <tr
                  key={agent.agent_id}
                  style={{
                    transition: 'background var(--transition-color)',
                    background: 'transparent',
                    opacity: rowOpacity,
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-raised)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                >
                  <td style={{ padding: 'var(--space-3) var(--space-4)', borderBottom: '1px solid var(--border-color)', fontSize: '14px', color: 'var(--text-primary)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: AGENT_COLORS[i % AGENT_COLORS.length] }}></span>
                      <span style={{ fontFamily: 'var(--font-data)', fontWeight: 500 }}>{agent.agent_id}</span>
                      {isDeleted && (
                        <span style={{
                          fontSize: '11px', color: 'var(--text-muted)', fontWeight: 400,
                          fontFamily: 'var(--font-body)', fontStyle: 'italic'
                        }}>
                          (Deleted)
                        </span>
                      )}
                    </div>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)', borderBottom: '1px solid var(--border-color)', fontSize: '14px', color: 'var(--text-primary)' }}>
                    {agent.session_count}
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)', borderBottom: '1px solid var(--border-color)', fontSize: '14px', color: 'var(--text-primary)' }}>
                    <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px' }}>{formatTokens(agent.total_tokens_in)}</span>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)', borderBottom: '1px solid var(--border-color)', fontSize: '14px', color: 'var(--text-primary)' }}>
                    <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px' }}>{formatTokens(agent.total_tokens_out)}</span>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)', borderBottom: '1px solid var(--border-color)', fontSize: '14px', color: 'var(--text-primary)' }}>
                    <span style={{ fontFamily: 'var(--font-data)', fontSize: '14px', fontWeight: 500, color: 'var(--accent-primary)' }}>
                      ${agent.total_cost.toFixed(2)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div style={{
          display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
          padding: 'var(--space-4) var(--space-5)', background: 'var(--bg-raised)', borderTop: '1px solid var(--border-color)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '14px', color: 'var(--text-secondary)' }}>
              Today: <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>{footerSessions}</strong> sessions
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '14px', color: 'var(--text-secondary)' }}>
              <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>{formatTokens(footerTokensIn)} in</strong> / <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>{formatTokens(footerTokensOut)} out</strong>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '14px', color: 'var(--text-secondary)' }}>
              Cost: <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>${footerCost.toFixed(2)}</strong>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 'var(--space-2)', borderTop: '1px solid var(--border-color)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '14px', color: 'var(--text-secondary)' }}>
              This Month: <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>{monthlySessions}</strong> sessions
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '14px', color: 'var(--text-secondary)' }}>
              <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>{formatTokens(monthlyTokensIn)} in</strong> / <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--text-primary)' }}>{formatTokens(monthlyTokensOut)} out</strong>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '14px', color: 'var(--text-secondary)' }}>
              Cost: <strong style={{ fontFamily: 'var(--font-data)', fontWeight: 500, color: 'var(--accent-primary)' }}>${monthlySpend.toFixed(2)}</strong>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
