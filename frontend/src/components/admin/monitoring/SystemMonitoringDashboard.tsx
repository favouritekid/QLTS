// src/components/admin/monitoring/SystemMonitoringDashboard.tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Database,
  Server,
  Workflow,
  Wifi,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { api } from "@/lib/api/client";

interface SystemOverview {
  timestamp: string;
  overall_status: "healthy" | "degraded";
  api: { status: string };
  database: { status: string; error?: string };
  redis: { status: string; connected_clients?: number; used_memory?: string; error?: string };
  celery: { status: string; workers?: number; active_tasks?: number; error?: string };
  socket_io: { status: string; active_connections?: number; error?: string };
  statistics: {
    total_users?: number;
    total_leads?: number;
    active_sessions?: number;
  };
}

interface CeleryWorker {
  name: string;
  status: string;
  active_tasks: number;
  registered_tasks: number;
}

interface SocketConnection {
  sid: string;
  user_id: number;
  username: string;
}

interface RedisInfo {
  status: string;
  server: {
    version: string;
    mode: string;
    uptime_days: number;
  };
  clients: {
    connected: number;
    blocked: number;
  };
  memory: {
    used: string;
    peak: string;
  };
  stats: {
    total_commands_processed: number;
    instantaneous_ops_per_sec: number;
    keyspace_hits: number;
    keyspace_misses: number;
  };
}

export function SystemMonitoringDashboard() {
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [refreshInterval] = useState(10000); // 10 seconds

  // System Overview Query
  const {
    data: overview,
    isLoading: overviewLoading,
    refetch: refetchOverview,
  } = useQuery<SystemOverview>({
    queryKey: ["system-overview"],
    queryFn: async () => {
      const response = await api.get("/api/monitoring/system/overview");
      return response.data;
    },
    refetchInterval: autoRefresh ? refreshInterval : false,
  });

  // Celery Workers Query
  const { data: celeryWorkers, isLoading: celeryLoading } = useQuery({
    queryKey: ["celery-workers"],
    queryFn: async () => {
      const response = await api.get("/api/monitoring/celery/workers");
      return response.data;
    },
    refetchInterval: autoRefresh ? refreshInterval : false,
  });

  // Redis Info Query
  const { data: redisInfo, isLoading: redisLoading } = useQuery<RedisInfo>({
    queryKey: ["redis-info"],
    queryFn: async () => {
      const response = await api.get("/api/monitoring/redis/info");
      return response.data;
    },
    refetchInterval: autoRefresh ? refreshInterval : false,
  });

  // Socket Connections Query
  const { data: socketConnections, isLoading: socketLoading } = useQuery({
    queryKey: ["socket-connections"],
    queryFn: async () => {
      const response = await api.get("/api/monitoring/socket/connections");
      return response.data;
    },
    refetchInterval: autoRefresh ? refreshInterval : false,
  });

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "ok":
      case "healthy":
      case "connected":
      case "online":
        return <CheckCircle className="h-5 w-5 text-green-500" />;
      case "degraded":
      case "no_workers":
        return <AlertTriangle className="h-5 w-5 text-yellow-500" />;
      case "error":
      case "unknown":
        return <XCircle className="h-5 w-5 text-red-500" />;
      default:
        return <Activity className="h-5 w-5 text-gray-500" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "ok":
      case "healthy":
      case "connected":
      case "online":
        return <Badge variant="default" className="bg-green-500">OK</Badge>;
      case "degraded":
      case "no_workers":
        return <Badge variant="secondary" className="bg-yellow-500">Warning</Badge>;
      case "error":
      case "unknown":
        return <Badge variant="destructive">Error</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Control Panel */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Monitoring Dashboard</CardTitle>
              <CardDescription>Real-time system health monitoring</CardDescription>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm text-muted-foreground">
                  Auto-refresh: {autoRefresh ? `${refreshInterval / 1000}s` : "Off"}
                </span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setAutoRefresh(!autoRefresh)}
              >
                {autoRefresh ? "Pause" : "Resume"}
              </Button>
              <Button variant="outline" size="sm" onClick={() => refetchOverview()}>
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Overall System Status Alert */}
      {overview && overview.overall_status === "degraded" && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>System Degraded</AlertTitle>
          <AlertDescription>
            One or more system components are experiencing issues. Check details below.
          </AlertDescription>
        </Alert>
      )}

      {/* System Overview Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {/* API Status */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">API Status</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {overviewLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  {getStatusIcon(overview?.api.status || "unknown")}
                  {getStatusBadge(overview?.api.status || "unknown")}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Database Status */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Database</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {overviewLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  {getStatusIcon(overview?.database.status || "unknown")}
                  {getStatusBadge(overview?.database.status || "unknown")}
                </div>
                {overview?.database.error && (
                  <p className="text-xs text-red-500">{overview.database.error}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Redis Status */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Redis Cache</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {overviewLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  {getStatusIcon(overview?.redis.status || "unknown")}
                  {getStatusBadge(overview?.redis.status || "unknown")}
                </div>
                {overview?.redis.connected_clients !== undefined && (
                  <p className="text-xs text-muted-foreground">
                    {overview.redis.connected_clients} clients
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Celery Status */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Celery Workers</CardTitle>
            <Workflow className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {overviewLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  {getStatusIcon(overview?.celery.status || "unknown")}
                  {getStatusBadge(overview?.celery.status || "unknown")}
                </div>
                {overview?.celery.workers !== undefined && (
                  <p className="text-xs text-muted-foreground">
                    {overview.celery.workers} worker(s)
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Statistics Cards */}
      {overview?.statistics && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Users</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{overview.statistics.total_users || 0}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Leads</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{overview.statistics.total_leads || 0}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active Sessions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{overview.statistics.active_sessions || 0}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Detailed Information Tabs */}
      <Tabs defaultValue="celery" className="space-y-4">
        <TabsList>
          <TabsTrigger value="celery">Celery Workers</TabsTrigger>
          <TabsTrigger value="redis">Redis Info</TabsTrigger>
          <TabsTrigger value="socket">Socket.IO</TabsTrigger>
        </TabsList>

        {/* Celery Workers Tab */}
        <TabsContent value="celery" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Celery Workers</CardTitle>
              <CardDescription>Active Celery workers and their status</CardDescription>
            </CardHeader>
            <CardContent>
              {celeryLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              ) : celeryWorkers?.workers && celeryWorkers.workers.length > 0 ? (
                <div className="space-y-4">
                  {celeryWorkers.workers.map((worker: CeleryWorker, index: number) => (
                    <div key={index} className="border rounded-lg p-4">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Workflow className="h-5 w-5" />
                          <h4 className="font-medium">{worker.name}</h4>
                        </div>
                        {getStatusBadge(worker.status)}
                      </div>
                      <div className="grid grid-cols-2 gap-4 text-sm">
                        <div>
                          <p className="text-muted-foreground">Active Tasks</p>
                          <p className="font-medium">{worker.active_tasks}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">Registered Tasks</p>
                          <p className="font-medium">{worker.registered_tasks}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <Alert>
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>No Workers Found</AlertTitle>
                  <AlertDescription>
                    No active Celery workers detected. Please check your Celery configuration.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Redis Info Tab */}
        <TabsContent value="redis" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Redis Information</CardTitle>
              <CardDescription>Redis server statistics and memory usage</CardDescription>
            </CardHeader>
            <CardContent>
              {redisLoading ? (
                <Skeleton className="h-40 w-full" />
              ) : redisInfo ? (
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <h4 className="font-medium">Server Info</h4>
                    <div className="text-sm space-y-1">
                      <p><span className="text-muted-foreground">Version:</span> {redisInfo.server.version}</p>
                      <p><span className="text-muted-foreground">Mode:</span> {redisInfo.server.mode}</p>
                      <p><span className="text-muted-foreground">Uptime:</span> {redisInfo.server.uptime_days} days</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <h4 className="font-medium">Clients</h4>
                    <div className="text-sm space-y-1">
                      <p><span className="text-muted-foreground">Connected:</span> {redisInfo.clients.connected}</p>
                      <p><span className="text-muted-foreground">Blocked:</span> {redisInfo.clients.blocked}</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <h4 className="font-medium">Memory</h4>
                    <div className="text-sm space-y-1">
                      <p><span className="text-muted-foreground">Used:</span> {redisInfo.memory.used}</p>
                      <p><span className="text-muted-foreground">Peak:</span> {redisInfo.memory.peak}</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <h4 className="font-medium">Statistics</h4>
                    <div className="text-sm space-y-1">
                      <p><span className="text-muted-foreground">Commands/sec:</span> {redisInfo.stats.instantaneous_ops_per_sec}</p>
                      <p><span className="text-muted-foreground">Total Commands:</span> {redisInfo.stats.total_commands_processed.toLocaleString()}</p>
                      <p><span className="text-muted-foreground">Cache Hit Rate:</span> {
                        redisInfo.stats.keyspace_hits + redisInfo.stats.keyspace_misses > 0
                          ? ((redisInfo.stats.keyspace_hits / (redisInfo.stats.keyspace_hits + redisInfo.stats.keyspace_misses)) * 100).toFixed(2)
                          : 0
                      }%</p>
                    </div>
                  </div>
                </div>
              ) : (
                <Alert variant="destructive">
                  <XCircle className="h-4 w-4" />
                  <AlertTitle>Redis Unavailable</AlertTitle>
                  <AlertDescription>Unable to connect to Redis server.</AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Socket.IO Tab */}
        <TabsContent value="socket" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Socket.IO Connections</CardTitle>
              <CardDescription>Active WebSocket connections</CardDescription>
            </CardHeader>
            <CardContent>
              {socketLoading ? (
                <Skeleton className="h-40 w-full" />
              ) : socketConnections ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                      <Wifi className="h-5 w-5" />
                      <span className="font-medium">
                        {socketConnections.total_connections} Total Connections
                      </span>
                    </div>
                    <Badge variant="outline">
                      {socketConnections.authenticated_connections} Authenticated
                    </Badge>
                  </div>

                  {socketConnections.connections && socketConnections.connections.length > 0 ? (
                    <div className="border rounded-lg divide-y max-h-96 overflow-y-auto">
                      {socketConnections.connections.map((conn: SocketConnection) => (
                        <div key={conn.sid} className="p-3 hover:bg-muted/50">
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="font-medium">{conn.username}</p>
                              <p className="text-xs text-muted-foreground">User ID: {conn.user_id}</p>
                            </div>
                            <Badge variant="secondary" className="text-xs">
                              {conn.sid.substring(0, 8)}...
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Alert>
                      <AlertDescription>No active Socket.IO connections</AlertDescription>
                    </Alert>
                  )}
                </div>
              ) : (
                <Alert variant="destructive">
                  <XCircle className="h-4 w-4" />
                  <AlertTitle>Socket.IO Unavailable</AlertTitle>
                  <AlertDescription>Unable to fetch Socket.IO connection info.</AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
