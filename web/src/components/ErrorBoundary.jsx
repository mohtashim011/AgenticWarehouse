/**
 * Error boundary
 * ==============
 * Stops one broken screen taking the whole application down with it.
 *
 * React unmounts the entire tree when a render throws and nothing catches it,
 * so a single undefined property on one page turned the app into a blank white
 * screen with no message and no way back. On a warehouse floor that is
 * indistinguishable from the server being down.
 *
 * The scanner is the reason this matters most: a blank page there means the
 * operator cannot record stock at all, and cannot tell anyone why.
 */
import * as React from "react";
import { AlertTriangle, RefreshCw, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Kept in the console rather than sent anywhere: this system is offline by
    // design, and a crash reporter would be the only thing in it phoning home.
    console.error("Screen failed to render:", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="mx-auto max-w-lg py-16 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/12">
          <AlertTriangle className="h-6 w-6 text-destructive" />
        </div>
        <h2 className="mt-4 text-lg font-semibold">This screen could not be shown</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Something went wrong rendering{" "}
          {this.props.name ? <b>{this.props.name}</b> : "this page"}. The rest of the
          system is unaffected — the sidebar still works, and nothing you have already
          scanned has been lost.
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg border bg-muted/40 p-3 text-left text-xs text-muted-foreground">
          {String(this.state.error?.message || this.state.error)}
        </pre>
        <div className="mt-6 flex justify-center gap-2">
          <Button variant="outline" onClick={() => window.history.back()}>
            <ArrowLeft className="h-4 w-4" />
            Go back
          </Button>
          <Button onClick={() => window.location.reload()}>
            <RefreshCw className="h-4 w-4" />
            Reload
          </Button>
        </div>
      </div>
    );
  }
}
