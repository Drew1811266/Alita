import { useCallback, useRef } from "react";

export type PendingPermissionChoiceSnapshot<
  TResearchChoice = unknown,
  TGraphOverwriteChoice = unknown,
> = {
  pendingResearchChoice: TResearchChoice | null;
  pendingGraphOverwriteChoice: TGraphOverwriteChoice | null;
};

export function createPendingPermissionChoiceSnapshot<
  TResearchChoice = unknown,
  TGraphOverwriteChoice = unknown,
>(): PendingPermissionChoiceSnapshot<TResearchChoice, TGraphOverwriteChoice> {
  return {
    pendingResearchChoice: null,
    pendingGraphOverwriteChoice: null,
  };
}

export function clearPendingPermissionChoices<
  TResearchChoice = unknown,
  TGraphOverwriteChoice = unknown,
>(
  _current?: PendingPermissionChoiceSnapshot<
    TResearchChoice,
    TGraphOverwriteChoice
  >,
): PendingPermissionChoiceSnapshot<TResearchChoice, TGraphOverwriteChoice> {
  return createPendingPermissionChoiceSnapshot<
    TResearchChoice,
    TGraphOverwriteChoice
  >();
}

export function usePermissionController<
  TResearchChoice = unknown,
  TGraphOverwriteChoice = unknown,
>() {
  const pendingResearchChoiceRef = useRef<TResearchChoice | null>(null);
  const pendingGraphOverwriteChoiceRef =
    useRef<TGraphOverwriteChoice | null>(null);

  const syncPendingPermissionChoices = useCallback(
    (
      snapshot: PendingPermissionChoiceSnapshot<
        TResearchChoice,
        TGraphOverwriteChoice
      >,
    ) => {
      pendingResearchChoiceRef.current = snapshot.pendingResearchChoice;
      pendingGraphOverwriteChoiceRef.current =
        snapshot.pendingGraphOverwriteChoice;
    },
    [],
  );

  const clearPendingPermissionChoiceRefs = useCallback(() => {
    syncPendingPermissionChoices(
      clearPendingPermissionChoices<
        TResearchChoice,
        TGraphOverwriteChoice
      >(),
    );
  }, [syncPendingPermissionChoices]);

  return {
    pendingResearchChoiceRef,
    pendingGraphOverwriteChoiceRef,
    syncPendingPermissionChoices,
    clearPendingPermissionChoices: clearPendingPermissionChoiceRefs,
  };
}
