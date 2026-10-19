import { memo } from 'react'
import { resetValidation, VIEWER_NOTE } from './api'
import { display, type ValidationSummary } from './live'

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour12: false })
}

function ValidationPanel({ validation, readOnly = false }: { validation: ValidationSummary | null; readOnly?: boolean }) {
  if (!validation) return null

  const clean = validation.withIssues === 0
  return (
    <section className="panel panel-wide">
      <h2>Validation</h2>
      <p className="muted">Protocol checks only: a warning, or a clean result, is not a safety verdict.</p>
      <p>
        Every message is checked against the VDA 5050 schemas and sequence rules (headerId, order sequence, mission
        state machine, topic consistency).
      </p>

      <div className="validation-totals">
        <div>
          <strong>{validation.checked}</strong>
          <span>messages checked</span>
        </div>
        <div>
          <strong className={clean ? 'clean' : 'dirty'}>{validation.withIssues}</strong>
          <span>with issues</span>
        </div>
        <div>
          <strong>{validation.byRule.length}</strong>
          <span>rules triggered</span>
        </div>
        <span className="muted">since {time(validation.since)}</span>
        <button type="button" disabled={readOnly} title={readOnly ? VIEWER_NOTE : undefined} onClick={() => resetValidation().catch(() => {})}>
          Reset counters
        </button>
      </div>

      {validation.byRule.length > 0 && (
        <div className="table-scroll">
          <table className="robot-table sessions-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Severity</th>
                <th>Count</th>
                <th>Latest</th>
              </tr>
            </thead>
            <tbody>
              {validation.byRule.map((rule) => (
                <tr key={rule.rule}>
                  <td className="mono" title={display(rule.description)}>
                    {display(rule.rule)}
                  </td>
                  <td>
                    <span className={`badge ${rule.severity === 'error' ? 'down' : 'warn'}`}>{rule.severity}</span>
                  </td>
                  <td className="mono">{display(rule.count)}</td>
                  <td className="error-text">
                    {rule.last && (
                      <>
                        <span className="mono muted">{time(rule.last.at)} </span>
                        {display(rule.last.message)}
                        <span className="mono muted"> · {display(rule.last.topic)}</span>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default memo(ValidationPanel)
