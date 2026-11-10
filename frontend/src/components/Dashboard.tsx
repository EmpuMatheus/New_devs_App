import React, { useEffect, useState } from "react";
import { SecureAPI } from "../lib/secureApi";
import { RevenueSummary } from "./RevenueSummary";

interface Property {
  id: string;
  name: string;
}

const Dashboard: React.FC = () => {
  const [properties, setProperties] = useState<Property[]>([]);
  const [selectedProperty, setSelectedProperty] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

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
                  Monthly performance insights for your properties
                </p>
              </div>

              {!loading && !error && properties.length > 0 && (
                <div className="flex flex-col sm:items-end">
                  <label className="text-xs font-medium text-gray-700 mb-1">Select Property</label>
                  <select
                    value={selectedProperty}
                    onChange={(e) => setSelectedProperty(e.target.value)}
                    className="block w-full sm:w-auto min-w-[200px] px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 text-sm"
                  >
                    {properties.map((property) => (
                      <option key={property.id} value={property.id}>
                        {property.name}
                      </option>
                    ))}
                  </select>
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
              <RevenueSummary propertyId={selectedProperty} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
