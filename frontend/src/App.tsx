import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Index from "./pages/Index";
import Home from "./pages/Home";
import Analytics from "./pages/Analytics";
import History from "./pages/History";
import Logs from "./pages/Logs";
import NotFound from "./pages/NotFound";
import PasswordGate from "./components/PasswordGate";
import Layout from "./components/Layout";
import { BotSocketProvider } from "./hooks/BotSocketContext";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <PasswordGate>
        <BrowserRouter>
          <BotSocketProvider>
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="/wallet" element={<Layout><Home /></Layout>} />
            <Route path="/analytics" element={<Layout><Analytics /></Layout>} />
            <Route path="/history" element={<Layout><History /></Layout>} />
            <Route path="/logs" element={<Layout><Logs /></Layout>} />
            {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
            <Route path="*" element={<NotFound />} />
          </Routes>
          </BotSocketProvider>
        </BrowserRouter>
      </PasswordGate>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
