import { Component, type ReactNode } from 'react'

type Props = { title: string; children: ReactNode }
type State = { error: Error | null }

/** Keeps one broken panel from blanking the whole lab; shows the error in its place. */
export default class PanelBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
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
