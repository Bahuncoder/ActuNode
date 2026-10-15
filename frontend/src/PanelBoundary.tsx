import { Component, type ReactNode } from 'react'

// resetKey: when it changes the panel renders its children again, so a panel recovers once the bad data is gone.
type Props = { title: string; children: ReactNode; resetKey?: unknown }
type State = { error: Error | null; resetKey: unknown }

/** Keeps one broken panel from blanking the whole lab; shows the error in its place. */
export default class PanelBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey === state.resetKey ? null : { error: null, resetKey: props.resetKey }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <section className="panel panel-wide">
        <h2>{this.props.title}</h2>
        <p className="error-text mono">This panel failed to render: {this.state.error.message}</p>
        <button type="button" className="link-button" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </section>
    )
  }
}
