import React, { useEffect, useState } from "react";
import { SecureAPI } from "../lib/secureApi";
import { RevenueSummary, RevenuePeriod } from "./RevenueSummary";

interface Property {
  id: string;
  name: string;
}

type ReportType = 'total' | 'monthly' | 'annual';

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const Dashboard: React.FC = () => {
  const [properties, setProperties] = useState<Property[]>([]);
  const [selectedProperty, setSelectedProperty] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const now = new Date();
  const [reportType, setReportType] = useState<ReportType>('total');
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  useEffect(() => {
    let cancelled = false;

    const loadProperties = async () => {
      try {
        setLoading(true);
        setError('');
        const response = await SecureAPI.getProperties({ page_size: 1000 });
        if (cancelled) return;

        const items: Property[] = (response?.data ?? []).map((property: any) => ({
          id: property.id,
          name: property.name,
        }));

        setProperties(items);
        setSelectedProperty(items[0]?.id ?? '');
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load properties:', err);
        setProperties([]);
        setSelectedProperty('');
        setError('Failed to load your properties');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadProperties();
    return () => { cancelled = true; };
  }, []);

  const period: RevenuePeriod = reportType === 'monthly'
    ? { type: 'monthly', year, month }
    : reportType === 'annual'
      ? { type: 'annual', year }
      : { type: 'total' };

  return (
    <div className="p-4 lg:p-6 min-h-full">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Property Management Dashboard</h1>

        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 lg:p-6">
          <div className="mb-6">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
              <div>
                <h2 className="text-lg lg:text-xl font-medium text-gray-900 mb-2">Revenue Overview</h2>
                <p className="text-sm lg:text-base text-gray-600">
                  Performance insights for your properties
                </p>
              </div>

              {!loading && !error && properties.length > 0 && (
                <div className="flex flex-col sm:items-end gap-3">
                  <div className="flex flex-wrap gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Select Property</label>
                      <select
                        value={selectedProperty}
                        onChange={(e) => setSelectedProperty(e.target.value)}
                        className="block w-full sm:w-auto min-w-[180px] px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                      >
                        {properties.map((property) => (
                          <option key={property.id} value={property.id}>
                            {property.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Report</label>
                      <select
                        value={reportType}
                        onChange={(e) => setReportType(e.target.value as ReportType)}
                        className="block w-full sm:w-auto px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                      >
                        <option value="total">All time</option>
                        <option value="monthly">Monthly</option>
                        <option value="annual">Annual</option>
                      </select>
                    </div>

                    {reportType !== 'total' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">Year</label>
                        <input
                          type="number"
                          min={1900}
                          max={2100}
                          value={year}
                          onChange={(e) => {
                            const value = parseInt(e.target.value, 10);
                            if (!Number.isNaN(value)) setYear(value);
                          }}
                          className="block w-28 px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                    )}

                    {reportType === 'monthly' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">Month</label>
                        <select
                          value={month}
                          onChange={(e) => setMonth(parseInt(e.target.value, 10))}
                          className="block w-full sm:w-auto px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                        >
                          {MONTH_NAMES.map((name, index) => (
                            <option key={name} value={index + 1}>{name}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-6">
            {loading && (
              <div className="animate-pulse space-y-4">
                <div className="h-4 bg-gray-100 rounded w-1/4"></div>
                <div className="h-8 bg-gray-100 rounded w-1/2"></div>
              </div>
            )}

            {!loading && error && (
              <div className="p-4 text-red-500 bg-red-50 rounded-lg">{error}</div>
            )}

            {!loading && !error && properties.length === 0 && (
              <div className="p-4 text-gray-500 bg-gray-50 rounded-lg">
                No properties are available for your account.
              </div>
            )}

            {!loading && !error && selectedProperty && (
              <RevenueSummary propertyId={selectedProperty} period={period} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
