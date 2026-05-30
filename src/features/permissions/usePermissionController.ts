import { useCallback, useRef } from "react";
import type { BackendEvent } from "../../shared/events";
import type { AuthorityDecisionRecord } from "../../shared/types";

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

export type AuthorityDecisionSnapshot = {
  authorityDecisions: AuthorityDecisionRecord[];
  latestDeniedAuthorityDecision: AuthorityDecisionRecord | null;
};

export function createAuthorityDecisionSnapshot(): AuthorityDecisionSnapshot {
  return {
    authorityDecisions: [],
    latestDeniedAuthorityDecision: null,
  };
}

export function reduceAuthorityDecisionSnapshotEvents(
  snapshot: AuthorityDecisionSnapshot,
  events: BackendEvent[],
): AuthorityDecisionSnapshot {
  return events.reduce<AuthorityDecisionSnapshot>((current, event) => {
    if (event.type !== "authority.decision_recorded") {
      return current;
    }

    const authorityDecisions = [
      ...current.authorityDecisions,
      event.payload.decision,
    ];
    return {
      authorityDecisions,
      latestDeniedAuthorityDecision: event.payload.decision.allowed
        ? current.latestDeniedAuthorityDecision
        : event.payload.decision,
    };
  }, snapshot);
}

export function usePermissionController<
  TResearchChoice = unknown,
  TGraphOverwriteChoice = unknown,
>() {
  const pendingResearchChoiceRef = useRef<TResearchChoice | null>(null);
  const pendingGraphOverwriteChoiceRef =
    useRef<TGraphOverwriteChoice | null>(null);
  const authorityDecisionSnapshotRef = useRef<AuthorityDecisionSnapshot>(
    createAuthorityDecisionSnapshot(),
  );

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

  const syncAuthorityDecisionSnapshot = useCallback(
    (snapshot: AuthorityDecisionSnapshot) => {
      authorityDecisionSnapshotRef.current = snapshot;
    },
    [],
  );

  const applyAuthorityDecisionEvents = useCallback((events: BackendEvent[]) => {
    authorityDecisionSnapshotRef.current = reduceAuthorityDecisionSnapshotEvents(
      authorityDecisionSnapshotRef.current,
      events,
    );
  }, []);

  return {
    pendingResearchChoiceRef,
    pendingGraphOverwriteChoiceRef,
    authorityDecisionSnapshotRef,
    syncPendingPermissionChoices,
    syncAuthorityDecisionSnapshot,
    applyAuthorityDecisionEvents,
    clearPendingPermissionChoices: clearPendingPermissionChoiceRefs,
  };
}
