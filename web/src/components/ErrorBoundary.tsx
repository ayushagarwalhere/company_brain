import { Component, type ErrorInfo, type ReactNode } from "react";

/** Contains a failing subtree (e.g. WebGL context loss in the 3D hero) instead of unmounting the whole app. */
export class ErrorBoundary extends Component<{ fallback?: ReactNode; onError?: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("Section failed and was replaced by its fallback:", error.message, info.componentStack?.split("\n")[1]?.trim());
    this.props.onError?.();
  }

  render() {
    return this.state.failed ? (this.props.fallback ?? null) : this.props.children;
  }
}
