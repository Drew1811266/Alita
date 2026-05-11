type ProjectHomeProps = {
  recentProjects: string[];
  error: string | null;
  onCreateProject(): void;
  onOpenProject(): void;
  onOpenPreferences(): void;
};

export function ProjectHome({
  recentProjects,
  error,
  onCreateProject,
  onOpenProject,
  onOpenPreferences,
}: ProjectHomeProps) {
  return (
    <main className="projectHome" aria-labelledby="project-home-title">
      <header className="projectHomeHeader">
        <div>
          <h1 id="project-home-title">Alita</h1>
          <p>创建或打开工程后进入 Agent 节点工作台。</p>
        </div>
        <button
          className="secondaryButton"
          onClick={onOpenPreferences}
          type="button"
        >
          首选项
        </button>
      </header>

      <section className="projectHomeGrid">
        <div className="projectStartPanel">
          <h2>开始</h2>
          <button
            className="primaryButton"
            onClick={onCreateProject}
            type="button"
          >
            新建工程
          </button>
          <button
            className="secondaryButton"
            onClick={onOpenProject}
            type="button"
          >
            打开工程
          </button>
          {error ? <p className="errorText">{error}</p> : null}
        </div>

        <div className="recentProjectsPanel">
          <h2>最近工程</h2>
          {recentProjects.length > 0 ? (
            <ul>
              {recentProjects.map((projectPath) => (
                <li key={projectPath}>{projectPath}</li>
              ))}
            </ul>
          ) : (
            <p>还没有最近工程。</p>
          )}
        </div>
      </section>
    </main>
  );
}
