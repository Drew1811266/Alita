import { useCallback, useMemo, useState } from "react";
import { getPreferences, type PreferencesView } from "./preferencesApi";

export type PreferencesControllerState = {
  preferences: PreferencesView | null;
  loading: boolean;
  error: string | null;
};

export function createPreferencesControllerState(): PreferencesControllerState {
  return { preferences: null, loading: false, error: null };
}

export function preferencesLoaded(
  state: PreferencesControllerState,
  preferences: PreferencesView,
): PreferencesControllerState {
  return { ...state, preferences, loading: false, error: null };
}

export function preferencesFailed(
  state: PreferencesControllerState,
  error: string,
): PreferencesControllerState {
  return { ...state, loading: false, error };
}

export function usePreferencesController() {
  const [state, setState] = useState(createPreferencesControllerState);

  const reloadPreferences = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const preferences = await getPreferences();
      setState((current) => preferencesLoaded(current, preferences));
      return preferences;
    } catch (error) {
      setState((current) => preferencesFailed(current, String(error)));
      throw error;
    }
  }, []);

  const setPreferences = useCallback((preferences: PreferencesView) => {
    setState((current) => preferencesLoaded(current, preferences));
  }, []);

  const setPreferencesError = useCallback((error: string | null) => {
    setState((current) => ({ ...current, error }));
  }, []);

  const setPreferencesLoading = useCallback((loading: boolean) => {
    setState((current) => ({ ...current, loading }));
  }, []);

  return useMemo(
    () => ({
      state,
      setState,
      reloadPreferences,
      setPreferences,
      setPreferencesError,
      setPreferencesLoading,
    }),
    [
      reloadPreferences,
      setPreferences,
      setPreferencesError,
      setPreferencesLoading,
      state,
    ],
  );
}
