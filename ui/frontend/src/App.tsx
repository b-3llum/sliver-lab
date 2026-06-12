import { Navigate, Route, Routes } from "react-router-dom";
import { AuthGate } from "@/components/AuthGate";
import { Layout } from "@/components/Layout";
import { ChromeStyles } from "@/components/chrome/ChromeStyles";
import { ToastHost } from "@/components/chrome/Toast";
import { LoadingBar } from "@/components/chrome/Loading";
import { Sessions } from "@/views/Sessions";
import { Console } from "@/views/Console";
import { Beacons } from "@/views/Beacons";
import { Graph } from "@/views/Graph";
import { Listeners } from "@/views/Listeners";
import { Jobs } from "@/views/Jobs";
import { Files } from "@/views/Files";
import { Loot } from "@/views/Loot";
import { Tunnels } from "@/views/Tunnels";
import { Build } from "@/views/Build";
import { Bofs } from "@/views/Bofs";
import { Profiles } from "@/views/Profiles";
import { Audit } from "@/views/Audit";
import { Report } from "@/views/Report";

export default function App() {
  return (
    <>
      <ChromeStyles />
      <ToastHost />
      <LoadingBar />
      <AuthGate>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/sessions" replace />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="console" element={<Console />} />
          {/* Backwards-compat: legacy /console/:sessionId redirects through ?open= */}
          <Route path="console/:sessionId" element={<Console />} />
          <Route path="beacons" element={<Beacons />} />
          <Route path="graph" element={<Graph />} />
          <Route path="listeners" element={<Listeners />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="files" element={<Files />} />
          <Route path="files/:sessionId" element={<Files />} />
          <Route path="loot" element={<Loot />} />
          <Route path="tunnels" element={<Tunnels />} />
          <Route path="build" element={<Build />} />
          <Route path="bofs" element={<Bofs />} />
          <Route path="profiles" element={<Profiles />} />
          <Route path="audit" element={<Audit />} />
          <Route path="report" element={<Report />} />
        </Route>
      </Routes>
      </AuthGate>
    </>
  );
}
