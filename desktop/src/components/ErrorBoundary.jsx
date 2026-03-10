/**
 * USTAT v5.4 Desktop — React Error Boundary.
 *
 * Yakalanmamis React renderlamasi hatalarinda
 * uygulamanin tamamen cokmesini onler.
 *
 * resetKey prop'u degistiginde hata durumu otomatik resetlenir.
 * Bu sayede route degisikliginde ErrorBoundary temizlenir ve
 * kullanici baska sayfalara gecebilir.
 */

import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  static getDerivedStateFromProps(props, state) {
    // resetKey degistiginde (ornegin route degisikligi) hata durumunu temizle
    if (state.hasError && props.resetKey !== state.lastResetKey) {
      return { hasError: false, error: null, lastResetKey: props.resetKey };
    }
    if (props.resetKey !== state.lastResetKey) {
      return { lastResetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] Yakalanmamis hata:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          padding: '2rem',
          textAlign: 'center',
          color: 'var(--text-primary, #e0e0e0)',
        }}>
          <h2 style={{ marginBottom: '1rem', color: 'var(--loss, #ef5350)' }}>
            Beklenmeyen Hata
          </h2>
          <p style={{ marginBottom: '0.5rem', color: 'var(--text-secondary, #aaa)' }}>
            {this.props.label
              ? `${this.props.label} sayfasinda bir hata olustu.`
              : 'Uygulama bir hatayla karsilasti.'}
          </p>
          <pre style={{
            maxWidth: '600px',
            padding: '1rem',
            borderRadius: '8px',
            background: 'var(--bg-secondary, #1a1a2e)',
            fontSize: '0.85rem',
            overflow: 'auto',
            marginBottom: '1.5rem',
            color: 'var(--text-secondary, #aaa)',
          }}>
            {this.state.error?.message || 'Bilinmeyen hata'}
          </pre>
          <button
            onClick={this.handleReset}
            style={{
              padding: '0.6rem 1.5rem',
              borderRadius: '6px',
              border: 'none',
              background: 'var(--accent, #4fc3f7)',
              color: '#000',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Tekrar Dene
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
