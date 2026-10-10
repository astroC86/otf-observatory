import { Component, type ReactNode } from "react";
import { EmptyState } from "../components/ui/EmptyState";
import { finishRender } from "../state/viewActions";

type Failure = { status: "none" } | { status: "caught"; message: string };
interface Props {
  epoch: number;
  children: ReactNode;
}
interface State {
  epoch: number;
  failure: Failure;
}
const NO_FAILURE: Failure = { status: "none" };

// React's native descendant-error API requires a class. This boundary alone
// uses it; feature and UI components remain functions, with no added wrapper DOM.
export class ViewErrorBoundary extends Component<Props, State> {
  state: State = { epoch: this.props.epoch, failure: NO_FAILURE };

  static getDerivedStateFromProps({ epoch }: Props, state: State): Partial<State> | null {
    return epoch === state.epoch ? null : { epoch, failure: NO_FAILURE };
  }

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return {
      failure: {
        status: "caught",
        message: error instanceof Error ? error.message : String(error),
      },
    };
  }

  componentDidCatch(error: Error): void {
    finishRender(this.props.epoch, performance.now(), error);
  }

  render(): ReactNode {
    return this.state.failure.status === "caught" ? (
      <EmptyState title="Unable to render this view" detail={this.state.failure.message} />
    ) : (
      this.props.children
    );
  }
}
