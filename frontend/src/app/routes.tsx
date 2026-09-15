import { createElement } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { LANDING_PATH } from '@/app/navigation';
import { OverallAnalysisPage } from '@/features/overall/pages/OverallAnalysisPage';
import { SeriesAnalysisPage } from '@/features/series-analysis/pages/SeriesAnalysisPage';
import { TrainingPage } from '@/features/training-explained/pages/TrainingPage';
import { ForecastingPage } from '@/features/forecasting/pages/ForecastingPage';
import { SupplyIntelligencePage } from '@/features/supply/pages/SupplyIntelligencePage';
import { AssistantPage } from '@/features/assistant/pages/AssistantPage';
import { RecommendationsPage } from '@/features/recommendations/pages/RecommendationsPage';

export function AppRoutes() {
  return (
    <Routes>
      <Route element={createElement(AppShell)} path="/">
        {/* `/` is not a destination of its own - it redirects, so an existing
            bookmark still lands somewhere real. */}
        <Route index element={createElement(Navigate, { to: LANDING_PATH, replace: true })} />
        <Route path="overall" element={createElement(OverallAnalysisPage)} />
        <Route path="series" element={createElement(SeriesAnalysisPage)} />
        <Route path="training" element={createElement(TrainingPage)} />
        <Route path="forecasting" element={createElement(ForecastingPage)} />
        <Route path="supply" element={createElement(SupplyIntelligencePage)} />
        <Route path="assistant" element={createElement(AssistantPage)} />
        <Route path="recommendations" element={createElement(RecommendationsPage)} />
        <Route
          path="*"
          element={createElement(Navigate, { to: LANDING_PATH, replace: true })}
        />
      </Route>
    </Routes>
  );
}
