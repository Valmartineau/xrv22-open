// web/src/calibrate/PartBoundary.tsx
// Error boundary isolant le chargement d'une pièce STL : si un useLoader échoue
// (ex. fetch interrompu par un redémarrage du dev server), seule cette pièce est
// masquée — la scène (sphères + autres pièces) continue de s'afficher.
import { Component, type ReactNode } from "react";

export class PartBoundary extends Component<
  { name: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(err: unknown) {
    console.warn(`[calibrate] échec de chargement STL "${this.props.name}":`, err);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
