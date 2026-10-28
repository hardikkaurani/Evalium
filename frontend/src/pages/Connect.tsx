import { useState, type FormEvent } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { Database, FlaskConical, KeyRound, ArrowRight, Mail, Lock, User, LogIn, UserPlus } from 'lucide-react';
import { useConnection } from '../context/ConnectionContext';
import { ThemeControl } from '../layouts/WorkspaceShell';
import { Button, ErrorNotice, Field } from '../components/ui';
import { client } from '../services/client';

export default function Connect() {
  const { connected, connect } = useConnection();
  const [searchParams] = useSearchParams();
  const [authMethod, setAuthMethod] = useState<'credentials' | 'apikey'>('credentials');
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const oauthError = searchParams.get('error');
  const getOAuthErrorMessage = (err: string | null): string | null => {
    if (!err) return null;
    switch (err) {
      case 'oauth_cancelled':
        return 'Google sign-in was cancelled.';
      case 'account_conflict':
        return 'Identity conflict: this email is already registered to a different Google account.';
      case 'invalid_state':
        return 'Authentication session expired or invalid state. Please try again.';
      case 'missing_parameters':
        return 'OAuth callback missing required parameters.';
      case 'exchange_failed':
        return 'Failed to exchange authorization code with Google.';
      case 'verification_failed':
        return 'Google identity verification failed.';
      default:
        return 'Google authentication failed. Please try again.';
    }
  };

  if (connected) return <Navigate to="/overview" replace />;

  const startGoogleLogin = () => {
    const backendUrl = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '');
    window.location.href = `${backendUrl}/auth/google/start`;
  };

  const submitApiKey = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await connect(key);
      setKey('');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const submitCredentials = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === 'register') {
        const resp = await client.post('/auth/register', {
          email: email.trim(),
          password,
          name: name.trim() || undefined,
        });
        const apiKey = resp.data?.data?.api_key;
        if (!apiKey) throw new Error('Registration failed: no session key returned.');
        await connect(apiKey);
      } else {
        const resp = await client.post('/auth/login', {
          email: email.trim(),
          password,
        });
        const apiKey = resp.data?.data?.api_key;
        if (!apiKey) throw new Error('Login failed: no session key returned.');
        await connect(apiKey);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page bg-[#F6F4EE] dark:bg-[#182026]">
      <section className="login-story bg-white dark:bg-[#202A32] border-r border-[#DDE4E1] dark:border-[#2E3A44]">
        <div className="flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 text-xs font-mono text-[#4C5F6B] dark:text-[#B0C2C6] hover:text-[#0284C7] transition-colors"
          >
            <span>← Back to Overview</span>
          </Link>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 flex items-center justify-center">
              <img
                src="/logo.png"
                alt="EvalForge"
                className="w-8 h-8 object-contain drop-shadow-sm"
              />
            </div>
            <span className="font-sans text-lg font-semibold text-[#2E3A44] dark:text-[#F6F4EE]">
              EvalForge
            </span>
          </div>
        </div>
        <div className="login-story-content">
          <h1>
            Better evaluations.
            <br />
            Clearer decisions.
          </h1>
          <p>
            A focused workspace for testing model responses, inspecting results, and tracking what
            changed.
          </p>
          <div style={{ marginTop: 44 }}>
            <div className="login-feature">
              <Database size={20} />
              <div>
                <h3>Start with your data</h3>
                <p>Organize prompts and reference answers in versioned datasets.</p>
              </div>
            </div>
            <div className="login-feature">
              <FlaskConical size={20} />
              <div>
                <h3>Inspect every result</h3>
                <p>Compare scores, review reasoning, and investigate failures.</p>
              </div>
            </div>
          </div>
        </div>
        <div className="login-story-footer muted" style={{ fontSize: 12 }}>
          Open source. Self-hosted. Connected to your infrastructure.
        </div>
      </section>
      <section className="login-form-area">
        <div className="login-form">
          <div style={{ marginBottom: 30 }}>
            <ThemeControl />
          </div>
          <h1>Connect your workspace</h1>
          <p>Sign in with Google, email, or a workspace API key.</p>
          {oauthError && (
            <div style={{ marginBottom: 16 }}>
              <ErrorNotice error={getOAuthErrorMessage(oauthError)} />
            </div>
          )}

          <button
            type="button"
            onClick={startGoogleLogin}
            className="w-full flex items-center justify-center gap-3 px-4 py-2.5 rounded-lg border border-[#DDE4E1] dark:border-[#3E4C59] bg-white dark:bg-[#202A32] text-[#2E3A44] dark:text-[#F6F4EE] font-medium text-sm hover:bg-[#F6F4EE] dark:hover:bg-[#2A3742] transition-colors shadow-sm mb-4 cursor-pointer"
            id="google-login-btn"
          >
            <svg
              className="w-4 h-4 shrink-0"
              viewBox="0 0 24 24"
              aria-hidden="true"
              focusable="false"
            >
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
              />
            </svg>
            <span>Continue with Google</span>
          </button>

          <div className="relative flex items-center justify-center my-4">
            <div className="border-t border-[#DDE4E1] dark:border-[#2E3A44] w-full" />
            <span className="bg-white dark:bg-[#202A32] px-3 text-xs text-[#4c5f6b] dark:text-[#b0c2c6] uppercase tracking-wider font-mono shrink-0">
              or {authMethod === 'credentials' ? 'continue with email' : 'continue with API key'}
            </span>
          </div>

          {authMethod === 'credentials' ? (
            <div className="auth-credentials-section">
              <div className="flex border-b border-[#DDE4E1] dark:border-[#2E3A44] mb-4">
                <button
                  type="button"
                  onClick={() => {
                    setMode('login');
                    setError(null);
                  }}
                  className={`pb-2 px-3 text-sm font-medium border-b-2 transition-colors ${
                    mode === 'login'
                      ? 'border-[#0284C7] text-[#0284C7] dark:text-[#38BDF8]'
                      : 'border-transparent text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#F1F5F9]'
                  }`}
                >
                  Sign In
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMode('register');
                    setError(null);
                  }}
                  className={`pb-2 px-3 text-sm font-medium border-b-2 transition-colors ${
                    mode === 'register'
                      ? 'border-[#0284C7] text-[#0284C7] dark:text-[#38BDF8]'
                      : 'border-transparent text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#F1F5F9]'
                  }`}
                >
                  Create Account
                </button>
              </div>

              <form className="form-stack" onSubmit={submitCredentials}>
                {error !== null && <ErrorNotice error={error} />}

                {mode === 'register' && (
                  <Field label="Full Name (optional)">
                    {(id) => (
                      <div className="relative">
                        <User className="absolute left-3 top-3 text-[#94A3B8]" size={16} />
                        <input
                          id={id}
                          className="control"
                          style={{ paddingLeft: '36px' }}
                          type="text"
                          autoComplete="name"
                          placeholder="Your name"
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                        />
                      </div>
                    )}
                  </Field>
                )}

                <Field label="Email Address">
                  {(id) => (
                    <div className="relative">
                      <Mail className="absolute left-3 top-3 text-[#94A3B8]" size={16} />
                      <input
                        id={id}
                        className="control"
                        style={{ paddingLeft: '36px' }}
                        type="email"
                        autoComplete="email"
                        required
                        placeholder="you@domain.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                      />
                    </div>
                  )}
                </Field>

                <Field label="Password">
                  {(id) => (
                    <div className="relative">
                      <Lock className="absolute left-3 top-3 text-[#94A3B8]" size={16} />
                      <input
                        id={id}
                        className="control"
                        style={{ paddingLeft: '36px' }}
                        type="password"
                        autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                        required
                        placeholder={mode === 'register' ? 'At least 8 characters' : 'Enter password'}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </div>
                  )}
                </Field>

                <Button
                  type="submit"
                  variant="primary"
                  busy={busy}
                  disabled={!email.trim() || !password}
                >
                  {mode === 'login' ? <LogIn size={16} /> : <UserPlus size={16} />}
                  {mode === 'login' ? 'Sign In' : 'Create Account'}
                  <ArrowRight size={16} />
                </Button>
              </form>

              <div className="text-center mt-4">
                <button
                  type="button"
                  onClick={() => {
                    setAuthMethod('apikey');
                    setError(null);
                  }}
                  className="text-xs text-[#0284C7] dark:text-[#38BDF8] hover:underline"
                >
                  Have a direct workspace API key? Connect with API key instead →
                </button>
              </div>
            </div>
          ) : (
            <div className="auth-apikey-section">
              <form className="form-stack" onSubmit={submitApiKey}>
                {error !== null && <ErrorNotice error={error} />}
                <Field
                  label="API key"
                  hint="Stored for this browser session only. Disconnect to remove it."
                >
                  {(id) => (
                    <input
                      id={id}
                      className="control mono"
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      required
                      placeholder="Enter your workspace API key (ef_...)"
                      value={key}
                      onChange={(e) => setKey(e.target.value)}
                    />
                  )}
                </Field>
                <Button type="submit" variant="primary" busy={busy} disabled={!key.trim()}>
                  <KeyRound size={16} />
                  Connect workspace
                  <ArrowRight size={16} />
                </Button>
              </form>

              <div className="text-center mt-4">
                <button
                  type="button"
                  onClick={() => {
                    setAuthMethod('credentials');
                    setError(null);
                  }}
                  className="text-xs text-[#0284C7] dark:text-[#38BDF8] hover:underline"
                >
                  ← Sign in or register with email & password
                </button>
              </div>
            </div>
          )}

          <details className="setup-help" style={{ marginTop: 24 }}>
            <summary>Authentication Options</summary>
            <p>
              <strong>Google Sign-In:</strong> Direct single-sign-on provisioning.
            </p>
            <p>
              <strong>Email & Password:</strong> Create a persistent workspace credentials account.
            </p>
            <p>
              <strong>Workspace API Key:</strong> Enter a pre-provisioned developer key.
            </p>
            <a
              href="https://github.com/hardikkaurani/Evalium/blob/main/docs/ui-setup.md"
              target="_blank"
              rel="noreferrer"
            >
              Read the setup guide
            </a>
          </details>
          <p className="muted" style={{ fontSize: 12, marginTop: 24 }}>
            Trouble connecting? Confirm that the backend is running and accessible from this
            browser.
          </p>
          <Link to="/login" className="sr-only">
            Connection page
          </Link>
        </div>
      </section>
    </div>
  );
}
