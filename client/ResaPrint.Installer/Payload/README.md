Empty by default. `.github/workflows/client-release.yml` copies the
published `ResaPrint.Agent.exe` and `ResaPrint.Tray.exe` here *before*
publishing this project, so `ResaPrint.Installer.csproj`'s
`<EmbeddedResource Include="Payload\*.exe">` picks them up and bundles
them into the installer's own single-file exe.

Nothing here is required for a plain `dotnet build`/`dotnet test` (the
wildcard glob just matches zero files) — only the release workflow
needs to populate this directory.
