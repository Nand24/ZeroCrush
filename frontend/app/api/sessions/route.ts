import { NextRequest, NextResponse } from 'next/server';
import prisma from '@/lib/prisma';
import { getRequestAuth } from '@/lib/server-auth';
import type { Prisma } from '@prisma/client';

function parseDateValue(value: unknown, fieldName: string): Date {
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid ${fieldName}`);
  }
  return date;
}

function parseNumberValue(value: unknown, fieldName: string): number {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) {
    throw new Error(`Invalid ${fieldName}`);
  }
  return number;
}

function normalizeSessionData(body: Record<string, unknown>): Prisma.SessionCreateInput {
  return {
    source: String(body.source ?? ''),
    startTime: parseDateValue(body.startTime, 'startTime'),
    endTime: parseDateValue(body.endTime, 'endTime'),
    videoFps: parseNumberValue(body.videoFps, 'videoFps'),
    processedFrameSize: parseNumberValue(body.processedFrameSize, 'processedFrameSize'),
    trackMaxAge: parseNumberValue(body.trackMaxAge, 'trackMaxAge'),
    tracksImageBase64: typeof body.tracksImageBase64 === 'string' ? body.tracksImageBase64 : null,
    heatmapImageBase64: typeof body.heatmapImageBase64 === 'string' ? body.heatmapImageBase64 : null,
    previewImageBase64: typeof body.previewImageBase64 === 'string' ? body.previewImageBase64 : null,
    crowdPeakBase64: typeof body.crowdPeakBase64 === 'string' ? body.crowdPeakBase64 : null,
    violationPeakBase64:
      typeof body.violationPeakBase64 === 'string'
        ? body.violationPeakBase64
        : (typeof body.alertPeakBase64 === 'string' ? body.alertPeakBase64 : null),
    crowdData: Array.isArray(body.crowdData) ? body.crowdData : null,
    energyBuckets: Array.isArray(body.energyBuckets) ? body.energyBuckets : null,
    logEvents: Array.isArray(body.logEvents) ? body.logEvents : null,
  } as Prisma.SessionCreateInput;
}

function parseSessionId(request: NextRequest): string | null {
  return request.nextUrl.searchParams.get('id');
}

export async function GET(request: NextRequest) {
  try {
    const auth = await getRequestAuth(request);
    if (!auth) {
      return NextResponse.json({ error: 'Authentication required.' }, { status: 401 });
    }
    const id = parseSessionId(request);
    if (id) 
    {
      const session = await prisma.session.findUnique({ where: { id } });
      if (!session) return NextResponse.json({ error: 'Not found' }, { status: 404 });
      return NextResponse.json(session);
    }

    const sessions = await prisma.session.findMany({
      orderBy: { createdAt: 'desc' },
    });

    return NextResponse.json({
      items: sessions,
    });
  } catch (error) {
    return NextResponse.json({ error: 'Failed to fetch sessions', details: String(error) }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const auth = await getRequestAuth(request);
    if (!auth) {
      return NextResponse.json({ error: 'Authentication required.' }, { status: 401 });
    }

    const body = (await request.json()) as Record<string, unknown>;
    const session = await prisma.session.create({ data: normalizeSessionData(body) });

    return NextResponse.json({ success: true, session }, { status: 201 });
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Invalid ')) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    return NextResponse.json({ error: 'Failed to save session', details: String(error) }, { status: 500 });
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const auth = await getRequestAuth(request);
    const id = parseSessionId(request);
    if (!auth || !id) {
      return NextResponse.json({ error: 'Authentication required or id missing' }, { status: 401 });
    }
    await prisma.session.delete({ where: { id } });
    return NextResponse.json({ success: true });
  } catch (error) {
    return NextResponse.json({ error: 'Failed to delete session', details: String(error) }, { status: 500 });
  }
}
