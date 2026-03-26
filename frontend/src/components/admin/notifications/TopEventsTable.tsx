"use client";

/**
 * D5: Top events by volume with fail rate column.
 */
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTopEvents } from "@/hooks/useNotificationDeliveries";

interface TopEventsTableProps {
  onEventClick?: (event: string) => void;
}

export default function TopEventsTable({ onEventClick }: TopEventsTableProps) {
  const { data, isLoading } = useTopEvents({ limit: 10 });

  const events = data?.events ?? [];

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Top Events (by volume)</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground py-4 text-center">Đang tải...</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">Chưa có dữ liệu</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Event</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Failed</TableHead>
                <TableHead className="text-right">Fail Rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((ev) => (
                <TableRow
                  key={ev.event}
                  className={onEventClick ? "cursor-pointer hover:bg-muted/50" : ""}
                  onClick={() => onEventClick?.(ev.event)}
                >
                  <TableCell className="font-mono text-xs">{ev.event}</TableCell>
                  <TableCell className="text-right">{ev.total}</TableCell>
                  <TableCell className="text-right text-red-600">{ev.failed}</TableCell>
                  <TableCell className="text-right">
                    <span className={ev.fail_rate > 0.1 ? "text-red-600 font-medium" : ""}>
                      {(ev.fail_rate * 100).toFixed(1)}%
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
